"""Running the UnderCover Agent: on one claim, or a dispatch over the queue."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, select

from backend import agent_service, db, grading, keys, runs, work
from backend.auth import SignedIn
from backend.db import Db, SingleStatementDb
from backend.db import runs as run_table
from backend.rules import find_claim
from backend.schemas import DispatchStart, RunRecord, StopReason

router = APIRouter(prefix="/api")


def thread_id_for(claim_id: str) -> str:
    """Return a new thread id for a run of the agent on a claim."""
    return f"{claim_id}-{uuid.uuid4().hex[:8]}"


# What the handler hears when the agent didn't take the work, or may have.
NOT_TAKEN_STATUS = 503
UNKNOWN_STATUS = 504


def ask_agent(payload: dict[str, Any]) -> dict[str, Any]:
    """Ask the agent to do some work, and return its answer when it took it."""
    return answered(agent_service.send(payload))


def taken(answer: agent_service.Answer) -> bool:
    """Whether the agent may have taken the work: it did, or nobody knows."""
    return answer.outcome in ("accepted", "unknown")


def answered(answer: agent_service.Answer) -> dict[str, Any]:
    """The agent's answer when it took the work. A refusal comes through as a 409
    saying why; work the agent didn't take as a 503, and a timeout, which may have
    started it, as a 504."""
    if answer.outcome == "refused":
        raise HTTPException(409, answer.detail or runs.ALREADY_RUNNING)
    if answer.outcome == "not_taken":
        raise HTTPException(NOT_TAKEN_STATUS, answer.detail)
    if answer.outcome == "unknown":
        raise HTTPException(UNKNOWN_STATUS, answer.detail)
    return answer.body


@router.post("/claims/{claim_id}/run", operation_id="run_claim")
def run_claim(claim_id: str, _: SignedIn, conn: Db) -> dict[str, str]:
    """Ask the agent's service to start on a waiting claim."""
    if find_claim(conn, claim_id)["status"] != "waiting":
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    thread_id = thread_id_for(claim_id)
    ask_agent({"operation": "work_claim", "claim_id": claim_id, "thread_id": thread_id})
    return {"claim_id": claim_id, "thread_id": thread_id}


def start_run(record: RunRecord) -> dict[str, Any]:
    """Create a dispatch or an evaluation, while nothing else of the agent's work is
    going, and ask the agent to work it. If the agent didn't take it, it's stopped."""
    with db.engine().begin() as conn:
        work.begin(conn)
        run_id = runs.start(conn, record)
    answer = agent_service.send({"operation": "work_run", "run_id": run_id})
    if not taken(answer):
        with db.engine().begin() as conn:
            work.stop_run(conn, run_id, answer.detail)
    answered(answer)
    return {"accepted": True, "run_id": run_id}


@router.post("/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(start: DispatchStart, _: SignedIn) -> dict[str, Any]:
    """Create a dispatch of the queue with N claim agents at once, for the agent."""
    record = RunRecord(
        kind="dispatch",
        n=start.n,
        set_name=None,
        tiny=False,
        version=None,
        round_id=None,
    )
    return start_run(record)


@router.post("/runs", operation_id="create_run", dependencies=keys.AGENT)
def create_run(record: RunRecord, conn: Db) -> dict[str, Any]:
    """Create one of a round's evaluations with its claims, for the agent."""
    if (record.kind == "evaluation") != (record.set_name is not None):
        raise HTTPException(422, "An evaluation, and only an evaluation, has a set")
    run_id = runs.start(conn, record)
    conn.commit()
    return describe_run(run_id, conn)


@router.get("/runs/current", operation_id="get_current_run", dependencies=keys.HANDLER)
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


@router.get("/runs/running", operation_id="get_running_run", dependencies=keys.READ)
def get_running_run(conn: SingleStatementDb) -> dict[str, Any] | None:
    """Get the dispatch or evaluation that is running, if there is one."""
    query = select(run_table).where(run_table.c.status == "running")
    row = conn.execute(query).mappings().first()
    return runs.describe(conn, row) if row else None


@router.get("/runs/{run_id}", operation_id="get_run", dependencies=keys.READ)
def get_run(run_id: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a dispatch or an evaluation: its claims, cost, time and summary."""
    return describe_run(run_id, conn)


def describe_run(run_id: int, conn: Connection) -> dict[str, Any]:
    """Return a run, or raise 404."""
    return runs.describe(conn, runs.find_run(conn, run_id))


@router.post(
    "/runs/{run_id}/finish", operation_id="finish_run", dependencies=keys.AGENT
)
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


@router.post("/runs/{run_id}/stop", operation_id="stop_run", dependencies=keys.AGENT)
def stop_run(run_id: int, stop: StopReason, conn: Db) -> dict[str, Any]:
    """Mark a run stopped with the reason, as the agent does when its work fails."""
    runs.end(conn, run_id, "stopped", stop.reason)
    conn.commit()
    return describe_run(run_id, conn)


@router.post(
    "/runs/{run_id}/heard", operation_id="hear_from_run", dependencies=keys.AGENT
)
def hear_from_run(run_id: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Note that the agent is still working on a run."""
    conn.execute(
        run_table.update().where(run_table.c.run_id == run_id).values(heard_at=db.now())
    )
    return {"run_id": run_id}
