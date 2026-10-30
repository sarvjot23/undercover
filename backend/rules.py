"""The claims rules: where a claim stands, how it moves, and the approval limit."""

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, Table, func, select

from backend import db
from backend.db import claims, decisions, steps

APPROVAL_LIMIT = float(db.load("company.json")["payout_approval_limit"])
MAX_ATTEMPTS = 2

LOOKUPS: dict[str, tuple[Table, str]] = {
    "policy": (db.policies, "policy_id"),
    "customer": (db.customers, "customer_id"),
    "plan": (db.plans, "plan"),
}


def record(conn: Connection, kind: str, key: str) -> Any:
    """Return one stored policy, customer or plan."""
    table, column = LOOKUPS[kind]
    query = select(table.c.body).where(table.c[column] == key)
    return json.loads(conn.execute(query).scalar_one())


def find_claim(conn: Connection, claim_id: str) -> RowMapping:
    """Return a claim's row, or raise 404."""
    query = select(claims).where(claims.c.claim_id == claim_id)
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"No claim {claim_id}")
    return row


def is_working(status: str, last_step: str | None) -> bool:
    """Whether the agent is still at work: in progress, or not yet given its answer."""
    return status == "in_progress" or last_step in ("tool_call", "tool_result", "read")


def agent_working(conn: Connection, row: RowMapping) -> bool:
    """Whether the agent is still at work on this claim."""
    query = (
        select(steps.c.kind)
        .where(steps.c.claim_id == row["claim_id"])
        .order_by(steps.c.step_id.desc())
        .limit(1)
    )
    return is_working(row["status"], conn.execute(query).scalar())


def last_steps(conn: Connection) -> dict[str, str]:
    """Return the kind of the latest step on every claim, in one query."""
    latest = select(func.max(steps.c.step_id)).group_by(steps.c.claim_id)
    query = select(steps.c.claim_id, steps.c.kind).where(steps.c.step_id.in_(latest))
    return {row["claim_id"]: row["kind"] for row in conn.execute(query).mappings()}


def decision_of(conn: Connection, claim_id: str) -> dict[str, Any] | None:
    """Return the decision on a claim, if there is one."""
    query = select(decisions).where(decisions.c.claim_id == claim_id)
    row = conn.execute(query).mappings().first()
    return dict(row) if row else None


def move(conn: Connection, claim_id: str, before: str, after: str) -> None:
    """Move a claim from one state to another, or raise 409."""
    find_claim(conn, claim_id)
    update = (
        claims.update()
        .where(claims.c.claim_id == claim_id, claims.c.status == before)
        .values(status=after)
    )
    if conn.execute(update).rowcount == 0:
        raise HTTPException(409, f"Claim {claim_id} is not {before}")


def add(conn: Connection, claim_id: str, kind: str, text: str) -> None:
    """Record one step of the agent's work."""
    conn.execute(
        steps.insert().values(claim_id=claim_id, kind=kind, text=text, at=db.now())
    )


def fail(conn: Connection, claim_id: str, reason: str) -> str:
    """Count a failed attempt on a claim in progress and say where it goes next.

    The first failure sends it back to the queue; the second leaves it for a handler.
    """
    attempts = find_claim(conn, claim_id)["attempts"] + 1
    after = "waiting" if attempts < MAX_ATTEMPTS else "needs_handler"
    move(conn, claim_id, "in_progress", after)
    conn.execute(
        claims.update().where(claims.c.claim_id == claim_id).values(attempts=attempts)
    )
    add(conn, claim_id, "error", reason)
    return after


def recover(conn: Connection) -> None:
    """Fail every claim a crash left in progress, so none stays stuck."""
    query = select(claims.c.claim_id).where(claims.c.status == "in_progress")
    for claim_id in conn.execute(query).scalars().all():
        fail(conn, claim_id, "The agent stopped partway")
    conn.commit()
