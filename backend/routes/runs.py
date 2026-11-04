"""Running the UnderCover Agent: on one claim, or a dispatch over the queue."""

import uuid
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, select

from backend import agent_service, db, grading, runs
from backend.auth import SignedIn
from backend.db import Db, SingleStatementDb
from backend.db import runs as run_table
from backend.rules import find_claim
from backend.schemas import DispatchStart, RunRecord

router = APIRouter(prefix="/api")

SERVICE_AWAY = "The agent's service isn't running"


def thread_id_for(claim_id: str) -> str:
    """Return a new thread id for a run of the agent on a claim."""
    return f"{claim_id}-{uuid.uuid4().hex[:8]}"


def ask_to_start(path: str, body: dict[str, object]) -> dict[str, bool]:
    """Ask the agent's service to start a run, passing on a refusal or its absence."""
    status = agent_service.ask(path, body)
    if status is None:
        raise HTTPException(503, SERVICE_AWAY)
    if status == HTTPStatus.CONFLICT:
        raise HTTPException(409, runs.ALREADY_RUNNING)
    return {"accepted": True}


@router.post("/claims/{claim_id}/run", operation_id="run_claim")
def run_claim(claim_id: str, _: SignedIn, conn: Db) -> dict[str, str]:
    """Ask the agent's service to start on a waiting claim."""
    if find_claim(conn, claim_id)["status"] != "waiting":
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    thread_id = thread_id_for(claim_id)
    if not agent_service.tell(f"/claims/{claim_id}/run", {"thread_id": thread_id}):
        raise HTTPException(503, SERVICE_AWAY)
    return {"claim_id": claim_id, "thread_id": thread_id}


@router.post("/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(start: DispatchStart, _: SignedIn) -> dict[str, bool]:
    """Ask the agent's service to dispatch the queue with N claim agents at once."""
    return ask_to_start("/dispatches", start.model_dump())


@router.post("/runs", operation_id="create_run")
def create_run(record: RunRecord, conn: Db) -> dict[str, Any]:
    """Create a dispatch or an evaluation with its claims, for the agent's service."""
    if (record.kind == "evaluation") != (record.set_name is not None):
        raise HTTPException(422, "An evaluation, and only an evaluation, has a set")
    run_id = runs.start(conn, record)
    conn.commit()
    return describe_run(run_id, conn)


@router.get("/runs/current", operation_id="get_current_run")
def get_current_run(conn: SingleStatementDb) -> dict[str, Any] | None:
    """Get the latest dispatch: its claims, cost, time and summary."""
    query = (
        select(run_table)
        .where(run_table.c.kind == "dispatch")
        .order_by(run_table.c.run_id.desc())
        .limit(1)
    )
    row = conn.execute(query).mappings().first()
    return runs.describe(conn, row) if row else None


@router.get("/runs/running", operation_id="get_running_run")
def get_running_run(conn: SingleStatementDb) -> dict[str, Any] | None:
    """Get the dispatch or evaluation that is running, if there is one."""
    query = select(run_table).where(run_table.c.status == "running")
    row = conn.execute(query).mappings().first()
    return runs.describe(conn, row) if row else None


@router.get("/runs/{run_id}", operation_id="get_run")
def get_run(run_id: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a dispatch or an evaluation: its claims, cost, time and summary."""
    return describe_run(run_id, conn)


def describe_run(run_id: int, conn: Connection) -> dict[str, Any]:
    """Return a run, or raise 404."""
    return runs.describe(conn, runs.find_run(conn, run_id))


@router.post("/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: int) -> dict[str, Any]:
    """Mark a run finished once its claims are worked, grading an evaluation's."""
    # The judge works with no connection held: there are only 4 to share.
    with db.engine().connect() as conn:
        row = runs.find_run(conn, run_id)
        grading_due = row["kind"] == "evaluation" and row["status"] == "running"
        work = grading.tasks(conn, row) if grading_due else []
    graded = grading.grade_all(work)
    with db.engine().begin() as conn:
        runs.end(conn, run_id, "finished")
        grading.save(conn, run_id, graded)
    with db.engine().connect() as conn:
        return describe_run(run_id, conn)


@router.post("/runs/{run_id}/stop", operation_id="stop_run")
def stop_run(run_id: int, conn: Db) -> dict[str, Any]:
    """Mark a run stopped, as the agent's service does with one left from before."""
    runs.end(conn, run_id, "stopped")
    conn.commit()
    return describe_run(run_id, conn)
