"""The dispatcher: works a run's claims with up to N claim agents at once, no model.

As in the Week 2 Day 4 lab: list the claims, fan out with one Send per claim, and
work each in a node of its own, with max_concurrency set to N. Each claim saves its
own progress on its own thread; the dispatcher saves none.
"""

import operator
import uuid
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy, Send

from agent import claim, client, graph, improver_client
from agent.tracing import Run

ATTEMPTS = 4
FIRST_WAIT = 5.0
NOT_STARTED = "not started, the round is stopped or has spent its limit"
FAILED = "The agent's work on it failed"
CUT_SHORT = "The round is stopped or has spent its limit"


class Dispatch(TypedDict):
    """What the dispatcher keeps for one run."""

    run: Run
    claims: list[str]
    results: Annotated[list[str], operator.add]


class Task(TypedDict):
    """One claim to work, and the run it's in."""

    claim_id: str
    run: Run


def list_claims(state: Dispatch) -> dict[str, Any]:
    """The run's claims, which the backend fixed when it created the run."""
    with client.backend() as backend:
        found = backend.get(f"/api/runs/{state['run']['run_id']}").json()
    return {"claims": [entry["claim_id"] for entry in found["claims"]]}


def fan_out(state: Dispatch) -> list[Send]:
    """Send each claim to a claim agent."""
    return [
        Send("work_claim", {"claim_id": claim_id, "run": state["run"]})
        for claim_id in state["claims"]
    ]


def leave_in_progress(claim_id: str, error: Exception) -> str:
    """Leave a claim that kept hitting rate limits or timeouts for the next dispatch."""
    text = f"The model kept failing ({error}); the next dispatch carries this claim on"
    graph.record_step(claim_id, "error", text, f"error-{uuid.uuid4().hex}")
    return f"{claim_id}: {text}"


def work_claim(state: Task, *, runtime: Runtime) -> dict[str, Any]:
    """Work one claim, and once more if it failed and went back to the queue.

    A rate limit or a timeout is waited out by the RetryPolicy, and the claim carries
    on from its last step. On the last attempt, this does what LangGraph's
    error_handler would: in LangGraph 1.2.12 an error_handler doesn't stop the error
    when other Send tasks run beside it, so the node handles its own last attempt.
    """
    claim_id = state["claim_id"]
    round_id = state["run"]["round_id"]
    if round_id is not None and not improver_client.may_go_on(round_id):
        return {"results": [f"{claim_id}: {NOT_STARTED}"]}
    try:
        report = claim.work(claim_id, state["run"])
        if graph.standing(claim_id)["status"] == "waiting":
            report = claim.work(claim_id, state["run"])
    except graph.PASSED_UP as error:
        attempt = runtime.execution_info
        if attempt is not None and attempt.node_attempt < ATTEMPTS:
            raise
        report = leave_in_progress(claim_id, error)
    except Exception as error:
        # Outside the claim's graph, such as the backend not answering in time: the
        # claim stays as it is for the next dispatch, and the others carry on.
        report = f"{claim_id}: stopped ({error!r}), the next dispatch carries it on"
    return {"results": [report]}


def build() -> Any:
    """Build the dispatcher's graph."""
    retry = RetryPolicy(
        max_attempts=ATTEMPTS,
        initial_interval=FIRST_WAIT,
        backoff_factor=2.0,
        jitter=True,
        retry_on=graph.PASSED_UP,
    )
    builder = StateGraph(Dispatch)
    builder.add_node("list_claims", list_claims)
    builder.add_node("work_claim", work_claim, retry_policy=retry)
    builder.add_edge(START, "list_claims")
    builder.add_conditional_edges("list_claims", fan_out, ["work_claim"])
    builder.add_edge("work_claim", END)
    return builder.compile()


def dispatch(run: Run, n: int) -> list[str]:
    """Work the run's claims, N at once, then tell the backend the run has finished.

    If the dispatcher itself breaks, the run is marked stopped, so the next can start.
    A round's evaluation cut short by its spending limit is stopped too.
    """
    path = f"/api/runs/{run['run_id']}"
    try:
        result = build().invoke({"run": run, "results": []}, {"max_concurrency": n})
    except Exception:
        with client.backend() as backend:
            backend.post(f"{path}/stop", json={"reason": FAILED})
        raise
    cut_short = any(NOT_STARTED in report for report in result["results"])
    with client.backend() as backend:
        if cut_short:
            backend.post(f"{path}/stop", json={"reason": CUT_SHORT})
        else:
            backend.post(f"{path}/finish")
    return result["results"]
