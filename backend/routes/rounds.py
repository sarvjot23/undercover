"""Rounds of improvement: the dashboard starts, stops and decides; the agent's
service does the work and records each step here."""

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from backend import agent_service, db, improver_view, rounds, versions
from backend.auth import over_the_limit
from backend.db import Db, SingleStatementDb
from backend.routes.runs import ask_to_start
from backend.schemas import (
    ChangeProposal,
    RecipeProposal,
    RecordedDecision,
    RoundDecision,
    RoundProgress,
    RoundStart,
    RoundUsage,
    Verdict,
)

INSTRUCTIONS = Path(__file__).parent.parent / "instructions" / "improver.md"

router = APIRouter(prefix="/api/rounds")

Starter = Annotated[dict[str, Any], Depends(over_the_limit("start a round"))]
Stopper = Annotated[dict[str, Any], Depends(over_the_limit("stop a round"))]
Decider = Annotated[
    dict[str, Any],
    Depends(over_the_limit("approve or reject the improver's proposals")),
]


def describe_round(round_id: int, conn: Any) -> dict[str, Any]:
    """A round as the dashboard shows it, or 404."""
    return rounds.describe(conn, rounds.find(conn, round_id))


# The dashboard's reads and a handler's actions.


@router.get("", operation_id="list_rounds")
def list_rounds(conn: SingleStatementDb) -> list[dict[str, Any]]:
    """List the rounds of improvement, newest first."""
    return rounds.listing(conn)


@router.get("/open", operation_id="get_open_round")
def get_open_round(conn: SingleStatementDb) -> dict[str, Any] | None:
    """Get the round that is open, working or waiting for a handler, if one is."""
    row = rounds.open_round(conn)
    return rounds.describe(conn, row) if row else None


@router.get("/{round_id}", operation_id="get_round")
def get_round(round_id: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a round: where it has got to, its proposal, verdict and cost."""
    return describe_round(round_id, conn)


@router.post("", operation_id="start_round", status_code=202)
def start_round(handler: Starter) -> dict[str, bool]:
    """Ask the agent's service to start a round of improvement."""
    return ask_to_start("/rounds", {"handler_id": handler["handler_id"]})


@router.post("/{round_id}/stop", operation_id="stop_round")
def stop_round(round_id: int, _: Stopper, conn: Db) -> dict[str, Any]:
    """Stop an open round; the service starts nothing more for it."""
    rounds.end(conn, round_id, "stopped")
    conn.commit()
    agent_service.tell(f"/rounds/{round_id}/stop", {})
    return describe_round(round_id, conn)


@router.post("/{round_id}/decision", operation_id="decide_on_proposal", status_code=202)
def decide_on_proposal(
    round_id: int, decision: RoundDecision, handler: Decider
) -> dict[str, bool]:
    """Approve or reject the proposal waiting; the service records it and resumes."""
    if decision.decision == "reject" and not decision.message.strip():
        raise HTTPException(422, "A rejection needs a reason for the improver")
    # No connection is held while the service records the decision through us.
    with db.engine().connect() as conn:
        waiting = rounds.find(conn, round_id)["proposal"]
    if waiting is None:
        raise HTTPException(409, f"Round {round_id} has nothing waiting for approval")
    body = {**decision.model_dump(), "handler_id": handler["handler_id"]}
    return ask_to_start(f"/rounds/{round_id}/decision", body)


# The agent's service records a round's work.


@router.post("/records", operation_id="create_round")
def create_round(start: RoundStart, conn: Db) -> dict[str, Any]:
    """Open a round on a copy of the settings, for the agent's service."""
    row = rounds.create(conn, start.handler_id)
    conn.commit()
    return rounds.describe(conn, row)


@router.get("/{round_id}/instructions", operation_id="get_improver_instructions")
def get_improver_instructions(round_id: int, conn: SingleStatementDb) -> dict[str, str]:
    """Get the improver's instructions, wrapped around the round's recipe."""
    row = rounds.find(conn, round_id)
    recipe = versions.find_recipe(conn, row["recipe_version"])["recipe"]
    text = INSTRUCTIONS.read_text(encoding="utf-8").replace("{recipe}", recipe)
    return {"instructions": text}


@router.get("/{round_id}/view", operation_id="read_round_results")
def read_round_results(round_id: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get what the improver reads: the current version, its scores and mistakes."""
    return improver_view.view(conn, rounds.find(conn, round_id))


@router.get("/{round_id}/first-evaluations", operation_id="list_first_evaluations")
def list_first_evaluations(round_id: int, conn: SingleStatementDb) -> dict[str, Any]:
    """List the whole-set evaluations the current version still needs."""
    rounds.find(conn, round_id)
    return {
        "version": versions.current(conn)["version"],
        "sets": rounds.first_evaluations(conn),
    }


@router.get("/{round_id}/spending", operation_id="get_round_spending")
def get_round_spending(round_id: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a round's limit, what it has spent, what's left and the next estimate."""
    return rounds.round_spending(conn, rounds.find(conn, round_id))


@router.post("/{round_id}/progress", operation_id="record_round_progress")
def record_round_progress(
    round_id: int, step: RoundProgress, conn: Db
) -> dict[str, Any]:
    """Record where a working round has got to."""
    rounds.progress(conn, round_id, step.stage, step.progress)
    conn.commit()
    return describe_round(round_id, conn)


@router.post("/{round_id}/proposals/change", operation_id="propose_change")
def propose_change(round_id: int, proposal: ChangeProposal, conn: Db) -> dict[str, Any]:
    """Record a change the improver proposes, to wait for a handler."""
    rounds.propose(conn, round_id, {"kind": "change", **proposal.model_dump()})
    conn.commit()
    return describe_round(round_id, conn)


@router.post("/{round_id}/proposals/recipe", operation_id="propose_recipe")
def propose_recipe(round_id: int, proposal: RecipeProposal, conn: Db) -> dict[str, Any]:
    """Record a new recipe the improver proposes, to wait for a handler."""
    rounds.propose(conn, round_id, {"kind": "recipe", **proposal.model_dump()})
    conn.commit()
    return describe_round(round_id, conn)


@router.post("/{round_id}/decisions", operation_id="record_decision_on_proposal")
def record_decision_on_proposal(
    round_id: int, decision: RecordedDecision, conn: Db
) -> dict[str, Any]:
    """Record a handler's decision on a proposal, before the improver resumes."""
    rounds.decide(
        conn, round_id, decision.decision, decision.message, decision.handler_id
    )
    conn.commit()
    return describe_round(round_id, conn)


@router.post("/{round_id}/verdict", operation_id="judge_round_version")
def judge_round_version(round_id: int, verdict: Verdict, conn: Db) -> dict[str, Any]:
    """Keep the version tried or roll it back by our rule."""
    rounds.judge_version(conn, round_id, verdict.unaffordable)
    conn.commit()
    return describe_round(round_id, conn)


@router.post("/{round_id}/finish", operation_id="finish_round")
def finish_round(round_id: int, conn: Db) -> dict[str, Any]:
    """Mark a round finished once the improver has done."""
    rounds.end(conn, round_id, "finished")
    conn.commit()
    return describe_round(round_id, conn)


@router.post("/{round_id}/halt", operation_id="halt_round")
def halt_round(round_id: int, conn: Db) -> dict[str, Any]:
    """Mark a round stopped, as the agent's service does with one left working."""
    rounds.end(conn, round_id, "stopped")
    conn.commit()
    return describe_round(round_id, conn)


@router.post("/{round_id}/usage", operation_id="record_improver_usage")
def record_improver_usage(
    round_id: int, reply: RoundUsage, conn: SingleStatementDb
) -> dict[str, Any]:
    """Record one of the improver's replies: its tokens and cost, once per key."""
    rounds.writable(conn, round_id)
    rounds.record_usage(conn, round_id, reply.model_dump())
    return {"round_id": round_id, "key": reply.key}
