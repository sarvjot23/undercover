"""The claim agent: works one claim on its graph and reports back in a line."""

import uuid
from contextvars import Context
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent import checkpoints, client, graph, lease, memory, routes, tracing
from agent.model import model
from agent.tools import ClaimContext
from agent.tracing import Run

NO_DECISION = "The agent finished without recording a decision"


def clock() -> datetime:
    """The time now, in UTC."""
    return datetime.now(UTC)


def fail(claim_id: str, reason: str) -> str:
    """Count a failed attempt and say where the claim goes next."""
    with client.backend() as backend:
        status = backend.post(
            f"/api/claims/{claim_id}/fail", json={"reason": reason}
        ).json()["status"]
    where = "back in the queue" if status == "waiting" else "left for a handler"
    return f"{claim_id}: failed ({reason}), {where}"


def build(llm: BaseChatModel | None, claim_id: str, run: Run | None) -> Any:
    """Build a claim's graph from its run's version of the configuration, or the
    current one, on the route and with the memory the settings give now."""
    version = version_of(run)
    path = "current" if version is None else f"versions/{version}"
    with client.backend() as backend:
        config = backend.get(f"/api/configuration/{path}").json()
        found = backend.get(f"/api/claims/{claim_id}").json()
    kind = run["kind"] if run else None
    claim = ClaimContext(
        claim_id=claim_id,
        policy_id=found["policy_id"],
        customer_id=found["customer_id"],
        version=config["version"],
        kind=kind,
        route=routes.choose(),
        memory=memory.for_run(kind),
    )
    return graph.build(
        lambda: llm or model(config["model"], config["reasoning"]),
        config["instructions"],
        checkpoints.saver(),
        claim,
    )


def version_of(run: Run | None) -> int | None:
    """The version a run works on; outside a run, the current one."""
    return run["version"] if run else None


def first_input(claim_id: str, thread_id: str) -> dict[str, Any]:
    """The state a claim starts from."""
    return {
        "messages": [HumanMessage(f"Decide claim {claim_id}.")],
        "claim_id": claim_id,
        "thread_id": thread_id,
        "model_calls": 0,
        "remembered": False,
    }


def record_time(
    claim_id: str, run: Run | None, started: datetime, finished: datetime
) -> None:
    """Record a spell of the agent's work on a claim, with its run."""
    with client.backend() as backend:
        backend.post(
            f"/api/claims/{claim_id}/work",
            json={
                "run_id": run["run_id"] if run else None,
                "started": started.isoformat(),
                "finished": finished.isoformat(),
            },
        )


def invoke(
    claim_graph: Any, claim_id: str, thread_id: str, start: Any, run: Run | None
) -> str:
    """Run the graph and report; an error sends back only a claim with no decision.

    A rate limit or a timeout goes up to the dispatcher, which waits and carries on.
    The time stops when the graph does, so a wait for a sign-off is never counted.
    """
    config = tracing.config(thread_id, graph.RECURSION_LIMIT, run)
    started = clock()
    try:
        # A clean context: inside the dispatcher, the graph would otherwise be
        # traced as a child of the dispatch, and not as a session of its own.
        Context().run(claim_graph.invoke, start, config, durability="sync")
    except graph.PASSED_UP:
        raise
    except Exception as error:
        if graph.standing(claim_id)["decision"] is None:
            return fail(claim_id, f"The agent's run failed: {error}")
        return f"{claim_id}: stopped after its decision ({error}), carries on next time"
    finally:
        record_time(claim_id, run, started, clock())
        tracing.flush()
    claim = graph.standing(claim_id)
    if claim["status"] == "in_progress" and claim["decision"] is None:
        return fail(claim_id, NO_DECISION)
    return graph.report(claim)


def run(
    claim_id: str,
    thread_id: str,
    llm: BaseChatModel | None = None,
    in_run: Run | None = None,
) -> str:
    """Start a waiting claim on a new thread and report back in a line."""
    with lease.holding(f"/api/claims/{claim_id}/lease") as held:
        if not held:
            return f"{claim_id}: not started, another worker is on it"
        with client.backend() as backend:
            started = backend.post(
                f"/api/claims/{claim_id}/start", json={"thread_id": thread_id}
            )
        if not started.is_success:
            return f"{claim_id}: not started, {client.reply(started)}"
        start = first_input(claim_id, thread_id)
        claim_graph = build(llm, claim_id, in_run)
        return invoke(claim_graph, claim_id, thread_id, start, in_run)


def carry_on(
    claim_id: str,
    llm: BaseChatModel | None = None,
    in_run: Run | None = None,
    worker: str | None = None,
) -> str:
    """Pick up a stopped claim from its last step, on the same thread.

    A paused claim resumes with the handler's answer: a signed-off claim is already
    paid, so its work only closes, and a sent-back claim is decided again. A worker
    that took a sent-back claim already holds its lease.
    """
    with lease.holding(f"/api/claims/{claim_id}/lease", worker) as held:
        if not held:
            return f"{claim_id}: not picked up, another worker is on it"
        claim = graph.standing(claim_id)
        signed_off = claim["sign_off"] is not None
        if claim["status"] != "in_progress" and not signed_off:
            return graph.report(claim)
        thread_id = claim["thread_id"]
        claim_graph = build(llm, claim_id, in_run)
        saved = claim_graph.get_state({"configurable": {"thread_id": thread_id}})
        start: Any = None
        if saved.interrupts:
            start = Command(resume=answer(claim))
        elif signed_off:
            return graph.report(claim)
        elif saved.values and not saved.next:
            return fail(claim_id, NO_DECISION)
        elif not saved.values:
            # A sent-back claim whose saved progress is gone starts afresh, with
            # the handler's note.
            start = first_input(claim_id, thread_id)
            returned = sent_back(claim_id)
            if returned:
                start["messages"].append(handler_message(returned[-1]))
        return invoke(claim_graph, claim_id, thread_id, start, in_run)


def sent_back(claim_id: str) -> list[dict[str, Any]]:
    """The claim's decisions sent back by a handler, oldest first, with their notes."""
    with client.backend() as backend:
        return backend.get(f"/api/claims/{claim_id}/sent-back").json()


def handler_message(returned: dict[str, Any]) -> HumanMessage:
    """The message carrying a handler's note. It's written here in the agent's code,
    not in its instructions, so a new version of the instructions can't drop it."""
    return HumanMessage(
        f"{returned['handler_name']}, a senior handler, sent your decision back to "
        f"you with this note:\n\n{returned['note']}\n\n"
        "Your earlier decision is withdrawn and nothing has been paid. Treat the note "
        "as a senior handler's review of your decision: check what it asks against "
        "the policy wording and the claims manual, like everything else, then record "
        "a new decision with record_decision. If the wording doesn't support what the "
        "note asks, refer the claim to a handler and give the reason."
    )


def answer(claim: dict[str, Any]) -> dict[str, Any]:
    """The handler's answer to a paused claim, from the app's record: a sign-off, or
    the latest decision sent back with its note."""
    if claim["sign_off"] is not None:
        return {"signed_off_by": claim["sign_off"]["handler_id"]}
    return {"message": handler_message(sent_back(claim["claim_id"])[-1]).text}


def take(claim_id: str) -> str | None:
    """Take a sent-back claim for work with a new worker, holding its lease; None if
    another caller took it first."""
    worker = uuid.uuid4().hex
    with client.backend() as backend:
        taken = backend.post(f"/api/claims/{claim_id}/take", json={"worker": worker})
    return worker if taken.is_success else None


def paused(claim_id: str) -> bool:
    """Whether a claim's thread has a pause waiting for a handler's answer."""
    thread_id = graph.standing(claim_id)["thread_id"]
    if thread_id is None:
        return False
    saved = build(None, claim_id, None).get_state(
        {"configurable": {"thread_id": thread_id}}
    )
    return bool(saved.interrupts)


def new_thread(claim_id: str) -> str:
    """Return a new thread id for a claim."""
    return f"{claim_id}-{uuid.uuid4().hex[:8]}"


def work(claim_id: str, in_run: Run | None, llm: BaseChatModel | None = None) -> str:
    """The one door to the claim agent: carry on a claim, take a sent-back one, or
    start a waiting one.

    An evaluation's copy never pauses for a sign-off: nobody signs off a copy.
    """
    status = graph.standing(claim_id)["status"]
    if status == "sent_back":
        worker = take(claim_id)
        if worker is None:
            return f"{claim_id}: not picked up, another worker took it"
        return carry_on(claim_id, llm, in_run, worker)
    if status == "in_progress":
        return carry_on(claim_id, llm, in_run)
    return run(claim_id, new_thread(claim_id), llm, in_run)
