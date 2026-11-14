"""Waiting for the agent's work, and checking our success criteria.

The Copilot waits in code, reading the run from the app every few seconds, and
never by calling the model again and again. Every figure in the success criteria is
worked out here from our records, never by the model.
"""

import time
from typing import Any

from langchain_core.tools import tool

from agent.copilot_client import Refused
from agent.copilot_tools import CopilotContext, Runtime, as_text, ask

POLL_SECONDS = 5
WAIT_SECONDS = 15 * 60
STRAIGHT_THROUGH_TARGET = 0.7
FOLLOW = {"dispatch": "the queue page", "evaluation": "the Scoreboard"}
# The clock and the pause between reads, which the tests replace.
clock = time.monotonic
pause = time.sleep


def wait(context: CopilotContext, run_id: int) -> dict[str, Any]:
    """Read the run every few seconds until it ends or 15 minutes pass."""
    began = clock()
    while True:
        run = ask(context, "GET", f"/api/runs/{run_id}")
        if run["status"] != "running" or clock() - began >= WAIT_SECONDS:
            return run
        pause(POLL_SECONDS)


def still_going(run: dict[str, Any]) -> str:
    """What to say when the work outlasts the wait."""
    return (
        f"{run['kind'].capitalize()} {run['run_id']} is still going after 15 minutes. "
        f"Follow it on {FOLLOW[run['kind']]}."
    )


def needs_a_handler(context: CopilotContext) -> dict[str, Any]:
    """What needs a handler in the queue: payouts held for sign-off, claims referred
    or left for a handler, and claims sent back that the agent hasn't worked."""
    queue = ask(context, "GET", "/api/claims")
    return {
        "held_for_sign_off": [
            {
                "claim_id": c["claim_id"],
                "customer": c["customer_name"],
                "payout": c["payout"],
            }
            for c in queue
            if c["status"] == "awaiting_sign_off"
        ],
        "referred": [
            c["claim_id"]
            for c in queue
            if c["status"] == "decided" and c["decision"] == "refer"
        ],
        "left_for_a_handler": [
            c["claim_id"] for c in queue if c["status"] == "needs_handler"
        ],
        "sent_back_not_worked_yet": [
            c["claim_id"] for c in queue if c["status"] == "sent_back"
        ],
    }


@tool
def wait_for_work(run_id: int, runtime: Runtime) -> str:
    """Wait for a dispatch or an evaluation you started to end, up to 15 minutes,
    then say how it went and, after a dispatch, what needs the handler."""
    context = runtime.context
    try:
        run = wait(context, run_id)
    except Refused as refused:
        return str(refused)
    if run["status"] == "running":
        return still_going(run)
    found: dict[str, Any] = {
        "run_id": run_id,
        "kind": run["kind"],
        "status": run["status"],
        "stop_reason": run.get("stop_reason"),
        "claims": len(run["claims"]),
        "cost": run["cost"],
        "elapsed_seconds": run["elapsed"],
    }
    if run["kind"] == "dispatch":
        found["summary"] = run["summary"]
        found["needs_you"] = needs_a_handler(context)
    else:
        found["measures"] = ask(context, "GET", f"/api/evaluations/{run_id}/measures")[
            "scores"
        ]
    return as_text(found)


def percent(share: float) -> str:
    """A share as a whole percentage, such as 84%."""
    return f"{share:.0%}"


def held_out_figures(context: CopilotContext) -> tuple[dict[str, Any] | None, str]:
    """Evaluate the whole held-out set with the agents in our settings, and give its
    measures, or none and why."""
    agents = ask(context, "GET", "/api/settings")["settings"]["agents_at_once"]
    body = {"set_name": "held_out", "tiny": False, "n": agents}
    try:
        run_id = ask(context, "POST", "/api/evaluations", body)["run_id"]
    except Refused as refused:
        return None, f"The evaluation didn't start: {refused.detail}"
    run = wait(context, run_id)
    if run["status"] == "running":
        return None, still_going(run)
    if run["status"] != "finished":
        why = run.get("stop_reason") or run["status"]
        return None, f"Evaluation {run_id} {run['status']} partway: {why}"
    measures = ask(context, "GET", f"/api/evaluations/{run_id}/measures")
    if not measures["scores"]:
        return None, f"Evaluation {run_id} has no measures"
    return {**measures["scores"], "run_id": run_id}, f"Evaluation {run_id}"


def criteria(context: CopilotContext) -> dict[str, Any]:
    """Each criterion's target, figure and whether it's met, worked out in code."""
    scores, source = held_out_figures(context)
    objective = ask(context, "GET", "/api/settings")["settings"]["objectives"][
        "accuracy"
    ]
    over = ask(context, "GET", "/api/payouts/over-limit")
    rows = []
    if scores is None:
        for name, target in (
            ("Straight through", f"at least {percent(STRAIGHT_THROUGH_TARGET)}"),
            ("Accuracy", f"at least {percent(objective)}"),
        ):
            rows.append(
                {"criterion": name, "target": target, "figure": None, "met": None}
            )
    else:
        rows.append(
            {
                "criterion": "Straight through",
                "target": f"at least {percent(STRAIGHT_THROUGH_TARGET)}",
                "figure": percent(scores["straight_through"]),
                "met": scores["straight_through"] >= STRAIGHT_THROUGH_TARGET,
            }
        )
        rows.append(
            {
                "criterion": "Accuracy",
                "target": f"at least {percent(objective)}",
                "figure": percent(scores["accuracy"]),
                "met": scores["accuracy"] >= objective,
            }
        )
    paid, signed = over["paid_over_limit"], over["signed_off"]
    limit = f"${over['approval_limit']:,.2f}"
    rows.append(
        {
            "criterion": "Over the limit",
            "target": f"every payout over {limit} signed off by a handler",
            "figure": (
                f"{signed} of {paid} signed off"
                if paid
                else f"none paid over {limit} yet, so none needed a sign-off"
            ),
            "met": signed == paid,
        }
    )
    known = [row["met"] for row in rows if row["met"] is not None]
    return {
        "from": source,
        "criteria": rows,
        "all_met": all(known) if len(known) == len(rows) else None,
    }


def as_table(found: dict[str, Any]) -> str:
    """The criteria as a small markdown table for the answer."""
    lines = ["| Criterion | Target | Figure | Met |", "| --- | --- | --- | --- |"]
    for row in found["criteria"]:
        met = {True: "Yes", False: "No", None: "Unknown"}[row["met"]]
        figure = row["figure"] or "No figure"
        lines.append(f"| {row['criterion']} | {row['target']} | {figure} | {met} |")
    return "\n".join(lines)


@tool
def check_success_criteria(runtime: Runtime) -> str:
    """Check the three success criteria we agreed: run an evaluation of the whole
    held-out set, wait for it, and work out each criterion from our records. Use
    its table and figures as they are."""
    try:
        found = criteria(runtime.context)
    except Refused as refused:
        return str(refused)
    return as_text({**found, "table": as_table(found)})
