"""Evaluations: the agent on copies of a labelled set, scored against our handlers."""

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from backend import measures, runs
from backend.auth import SignedIn
from backend.db import SingleStatementDb
from backend.db import runs as run_table
from backend.routes.runs import ask_to_start
from backend.schemas import EvaluationStart

router = APIRouter(prefix="/api/evaluations")


@router.post("", operation_id="start_evaluation", status_code=202)
def start_evaluation(start: EvaluationStart, _: SignedIn) -> dict[str, bool]:
    """Ask the agent's service to evaluate the agent on a labelled set."""
    return ask_to_start("/evaluations", start.model_dump())


@router.get("", operation_id="list_evaluations")
def list_evaluations(conn: SingleStatementDb) -> list[dict[str, Any]]:
    """List the evaluations, newest first, with their measures."""
    query = (
        select(run_table)
        .where(run_table.c.kind == "evaluation")
        .order_by(run_table.c.run_id.desc())
    )
    found = []
    for row in conn.execute(query).mappings().all():
        evaluation = measures.evaluation(conn, row)
        found.append({k: v for k, v in evaluation.items() if k != "claims"})
    return found


@router.get("/{run_id}", operation_id="get_evaluation")
def get_evaluation(run_id: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get an evaluation: each claim, the handler's answer beside the agent's."""
    row = runs.find_run(conn, run_id)
    if row["kind"] != "evaluation":
        raise HTTPException(404, f"No evaluation {run_id}")
    return measures.evaluation(conn, row)
