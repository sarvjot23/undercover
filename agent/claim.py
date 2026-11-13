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
    claim_id: str, llm: BaseChatModel | None = None, in_run: Run | None = None
) -> str:
    """Pick up a stopped claim from its last step, on the same thread.

    A signed-off claim is already paid: its paused work only closes.
    """
    with lease.holding(f"/api/claims/{claim_id}/lease") as held:
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
        if signed_off:
            if not saved.interrupts:
                return graph.report(claim)
            start = Command(resume=claim["sign_off"])
        elif saved.values and not saved.next:
            return fail(claim_id, NO_DECISION)
        elif not saved.values:
            start = first_input(claim_id, thread_id)
        return invoke(claim_graph, claim_id, thread_id, start, in_run)


def new_thread(claim_id: str) -> str:
    """Return a new thread id for a claim."""
    return f"{claim_id}-{uuid.uuid4().hex[:8]}"


def work(claim_id: str, in_run: Run | None, llm: BaseChatModel | None = None) -> str:
    """The one door to the claim agent: carry on a claim, or start a waiting one.

    An evaluation's copy held for sign-off counts as finished: nobody signs off a
    copy, so its saved progress is cleared.
    """
    if graph.standing(claim_id)["status"] == "in_progress":
        report = carry_on(claim_id, llm, in_run)
    else:
        report = run(claim_id, new_thread(claim_id), llm, in_run)
    found = graph.standing(claim_id)
    if found["evaluation_id"] is not None and found["status"] == "awaiting_sign_off":
        checkpoints.saver().delete_thread(found["thread_id"])
    return report
