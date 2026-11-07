"""What the agent's work on a claim costs: its model replies and its time."""

from typing import Any

from fastapi import APIRouter

from backend import keys
from backend.db import SingleStatementDb, usage, work_sessions
from backend.rules import find_claim, insert_once
from backend.schemas import Usage, WorkSession

router = APIRouter(prefix="/api/claims")


@router.post("/{claim_id}/usage", operation_id="record_usage", dependencies=keys.AGENT)
def record_usage(
    claim_id: str, reply: Usage, conn: SingleStatementDb
) -> dict[str, Any]:
    """Record a model reply's tokens and cost, once for each key."""
    find_claim(conn, claim_id)
    insert_once(conn, usage, claim_id=claim_id, **reply.model_dump())
    return {"claim_id": claim_id, "key": reply.key}


@router.post("/{claim_id}/work", operation_id="record_work", dependencies=keys.AGENT)
def record_work(
    claim_id: str, session: WorkSession, conn: SingleStatementDb
) -> dict[str, Any]:
    """Record a spell of the agent's work on a claim, with its run."""
    find_claim(conn, claim_id)
    seconds = (session.finished - session.started).total_seconds()
    conn.execute(
        work_sessions.insert().values(
            claim_id=claim_id,
            run_id=session.run_id,
            started=session.started.isoformat(),
            finished=session.finished.isoformat(),
            seconds=seconds,
        )
    )
    return {"claim_id": claim_id, "seconds": seconds}
