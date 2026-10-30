"""The rules for a queue run: its cap, its claims and when it may finish."""

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, select

from backend import db
from backend.db import claims, run_claims, runs
from backend.rules import fail, find_claim


def waiting(conn: Connection) -> list[str]:
    """Return the waiting claims in the order they were submitted."""
    query = select(claims.c.claim_id, claims.c.body).where(claims.c.status == "waiting")
    found = sorted(
        (json.loads(row["body"])["submitted_on"], row["claim_id"])
        for row in conn.execute(query).mappings()
    )
    return [claim_id for _, claim_id in found]


def describe(conn: Connection, row: RowMapping) -> dict[str, Any]:
    """Return a run with its claims in the order the agent took them."""
    query = (
        select(run_claims.c.claim_id)
        .where(run_claims.c.run_id == row["run_id"])
        .order_by(run_claims.c.position)
    )
    return {
        **dict(row),
        "todos": json.loads(row["todos"]),
        "claim_ids": list(conn.execute(query).scalars()),
    }


def find_run(conn: Connection, run_id: int) -> RowMapping:
    """Return a run that is still going, or raise 404 or 409."""
    query = select(runs).where(runs.c.run_id == run_id)
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"No run {run_id}")
    if row["status"] != "running":
        raise HTTPException(409, f"Run {run_id} is {row['status']}")
    return row


def start(conn: Connection, cap: int) -> int:
    """Start a run on up to cap waiting claims, unless one is already going."""
    if conn.execute(select(runs.c.run_id).where(runs.c.status == "running")).first():
        raise HTTPException(409, "The agent is already working through the queue")
    total = min(cap, len(waiting(conn)))
    result = conn.execute(
        runs.insert().values(
            cap=cap, total=total, status="running", todos="[]", started_at=db.now()
        )
    )
    return int(result.inserted_primary_key[0])  # type: ignore[index]


def take(conn: Connection, run_id: int, claim_id: str) -> int:
    """Add a waiting claim to the run, within its cap, and return its position."""
    run = find_run(conn, run_id)
    if find_claim(conn, claim_id)["status"] != "waiting":
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    taken = describe(conn, run)["claim_ids"]
    if claim_id in taken:
        return taken.index(claim_id) + 1
    if len(taken) >= run["cap"]:
        raise HTTPException(
            409, f"This run is capped at {run['cap']} claims and has taken them all"
        )
    conn.execute(
        run_claims.insert().values(
            run_id=run_id, claim_id=claim_id, position=len(taken) + 1
        )
    )
    return len(taken) + 1


def missed(conn: Connection, run_id: int) -> list[str]:
    """Return the waiting claims the run still has to work before it may finish."""
    run = find_run(conn, run_id)
    taken = describe(conn, run)["claim_ids"]
    queue = waiting(conn)
    retries = [claim_id for claim_id in taken if claim_id in queue]
    fresh = [claim_id for claim_id in queue if claim_id not in taken]
    return retries + fresh[: max(run["cap"] - len(taken), 0)]


def end(conn: Connection, run_id: int, status: str, summary: str) -> None:
    """End a run, failing any of its claims still in progress."""
    run = find_run(conn, run_id)
    for claim_id in describe(conn, run)["claim_ids"]:
        if find_claim(conn, claim_id)["status"] == "in_progress":
            fail(conn, claim_id, "The run ended while the agent was on this claim")
    conn.execute(
        runs.update()
        .where(runs.c.run_id == run_id)
        .values(status=status, summary=summary, finished_at=db.now())
    )
