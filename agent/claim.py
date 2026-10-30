"""The claim agent: works one claim on its graph and reports back in a line."""

from contextvars import Context
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent import checkpoints, client, graph, lease, tracing
from agent.model import model

NO_DECISION = "The agent finished without recording a decision"


def fail(claim_id: str, reason: str) -> str:
    """Count a failed attempt and say where the claim goes next."""
    with client.backend() as backend:
        status = backend.post(
            f"/api/claims/{claim_id}/fail", json={"reason": reason}
        ).json()["status"]
    where = "back in the queue" if status == "waiting" else "left for a handler"
    return f"{claim_id}: failed ({reason}), {where}"


def build(llm: BaseChatModel | None) -> Any:
    """Build the claim graph with the instructions the backend holds."""
    with client.backend() as backend:
        instructions = backend.get("/api/instructions").json()["claim"]
    return graph.build(lambda: llm or model(), instructions, checkpoints.saver())


def first_input(claim_id: str, thread_id: str) -> dict[str, Any]:
    """The state a claim starts from."""
    return {
        "messages": [HumanMessage(f"Decide claim {claim_id}.")],
        "claim_id": claim_id,
        "thread_id": thread_id,
        "model_calls": 0,
    }


def work(claim_graph: Any, claim_id: str, thread_id: str, start: Any) -> str:
    """Run the graph and report; an error sends back only a claim with no decision."""
    config = tracing.config(thread_id, graph.RECURSION_LIMIT)
    try:
        # A clean context: inside the queue agent's tool, the graph would otherwise be
        # traced as a child of the queue run, and not as a session of its own.
        Context().run(claim_graph.invoke, start, config, durability="sync")
    except Exception as error:
        if graph.standing(claim_id)["decision"] is None:
            return fail(claim_id, f"The agent's run failed: {error}")
        return f"{claim_id}: stopped after its decision ({error}), carries on next time"
    finally:
        tracing.flush()
    claim = graph.standing(claim_id)
    if claim["status"] == "in_progress" and claim["decision"] is None:
        return fail(claim_id, NO_DECISION)
    return graph.report(claim)


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
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
        return work(build(llm), claim_id, thread_id, first_input(claim_id, thread_id))


def carry_on(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Pick up a stopped or signed-off claim from its last step, on the same thread."""
    with lease.holding(f"/api/claims/{claim_id}/lease") as held:
        if not held:
            return f"{claim_id}: not picked up, another worker is on it"
        claim = graph.standing(claim_id)
        if claim["status"] != "in_progress":
            return graph.report(claim)
        thread_id = claim["thread_id"]
        claim_graph = build(llm)
        saved = claim_graph.get_state({"configurable": {"thread_id": thread_id}})
        if saved.values and not saved.next:
            return fail(claim_id, NO_DECISION)
        start: Any = None
        if saved.interrupts:
            start = Command(resume=claim["sign_off"])
        elif not saved.values:
            start = first_input(claim_id, thread_id)
        return work(claim_graph, claim_id, thread_id, start)
