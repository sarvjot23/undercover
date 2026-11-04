"""The claims rules: where a claim stands, how it moves, and the approval limit."""

import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, Select, Table, literal, select
from sqlalchemy.dialects.postgresql import insert

from backend import db
from backend.db import claims, decisions, payments, sign_offs, steps

APPROVAL_LIMIT = float(db.load("company.json")["payout_approval_limit"])
MAX_ATTEMPTS = 2

LOOKUPS: dict[str, tuple[Table, str]] = {
    "policy": (db.policies, "policy_id"),
    "customer": (db.customers, "customer_id"),
    "plan": (db.plans, "plan"),
}
RECORDS: dict[tuple[str, str], Any] = {}
PARTS: dict[str, Table] = {
    "decision": decisions,
    "payment": payments,
    "sign_off": sign_offs,
}


def record(conn: Connection, kind: str, key: str) -> Any:
    """Return a stored policy, customer or plan, reading each only once."""
    if (kind, key) not in RECORDS:
        table, column = LOOKUPS[kind]
        query = select(table.c.body).where(table.c[column] == key)
        RECORDS[kind, key] = json.loads(conn.execute(query).scalar_one())
    return RECORDS[kind, key]


def standing_query() -> Select[Any]:
    """Select a claim with all that's recorded on it, in one query.

    Supabase is a round trip away, so what the agent asks often costs a single query.
    """
    last_step = (
        select(steps.c.kind)
        .where(steps.c.claim_id == claims.c.claim_id)
        .order_by(steps.c.step_id.desc())
        .limit(1)
        .scalar_subquery()
        .label("last_step")
    )
    columns = [
        column.label(f"{name}_{column.name}")
        for name, table in PARTS.items()
        for column in table.c
    ]
    joined = claims
    for table in PARTS.values():
        joined = joined.outerjoin(table, table.c.claim_id == claims.c.claim_id)
    return select(claims, last_step, *columns).select_from(joined)


def standing_of(row: RowMapping) -> dict[str, Any]:
    """Turn a row of the standing query into a claim and what's recorded on it."""
    standing = {
        "claim_id": row["claim_id"],
        "status": row["status"],
        "attempts": row["attempts"],
        "thread_id": row["thread_id"],
        "agent_working": is_working(row["status"], row["last_step"]),
        "evaluation_id": row["evaluation_id"],
    }
    for name, table in PARTS.items():
        found = row[f"{name}_claim_id"] is not None
        standing[name] = (
            {column.name: row[f"{name}_{column.name}"] for column in table.c}
            if found
            else None
        )
    return standing


def find_standing(conn: Connection, claim_id: str) -> RowMapping:
    """Return a claim's row of the standing query, or raise 404."""
    query = standing_query().where(claims.c.claim_id == claim_id)
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"No claim {claim_id}")
    return row


def standing(conn: Connection, claim_id: str) -> dict[str, Any]:
    """Return where a claim stands and what's recorded on it, or raise 404."""
    return standing_of(find_standing(conn, claim_id))


def find_claim(conn: Connection, claim_id: str) -> RowMapping:
    """Return a claim's row, or raise 404."""
    query = select(claims).where(claims.c.claim_id == claim_id)
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"No claim {claim_id}")
    return row


def is_working(status: str, last_step: str | None) -> bool:
    """Whether the agent is at work: in progress, or not yet given its answer."""
    if status == "awaiting_sign_off":
        return False
    return status == "in_progress" or last_step in ("tool_call", "tool_result", "read")


def move(conn: Connection, claim_id: str, before: str, after: str) -> None:
    """Move a claim from one state to another, or raise 409."""
    update = (
        claims.update()
        .where(claims.c.claim_id == claim_id, claims.c.status == before)
        .values(status=after)
    )
    if conn.execute(update).rowcount == 0:
        find_claim(conn, claim_id)
        raise HTTPException(409, f"Claim {claim_id} is not {before}")


def insert_once(conn: Connection, table: Table, **values: Any) -> bool:
    """Insert a row unless it's already there, and say whether it was new.

    ON CONFLICT DO NOTHING reads the same on SQLite and Postgres.
    """
    statement = insert(table).values(**values).on_conflict_do_nothing()
    return conn.execute(statement).rowcount > 0


def add(conn: Connection, claim_id: str, kind: str, text: str, key: str) -> bool:
    """Record a step on a claim that exists, in one statement; a repeat key is ignored.

    Say whether a step was written.
    """
    values = select(
        claims.c.claim_id,
        literal(kind),
        literal(text),
        literal(key),
        literal(db.now()),
    ).where(claims.c.claim_id == claim_id)
    statement = (
        insert(steps)
        .from_select(["claim_id", "kind", "text", "key", "at"], values)
        .on_conflict_do_nothing()
    )
    return conn.execute(statement).rowcount > 0


def fail(conn: Connection, claim_id: str, reason: str) -> str:
    """Count a failed attempt on a claim in progress and say where it goes next.

    The first failure sends it back to the queue to start afresh; the second leaves
    it for a handler. A claim with a decision stands, so it can't fail.
    """
    found = standing(conn, claim_id)
    if found["decision"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has a decision and carries on")
    attempts = found["attempts"] + 1
    after = "waiting" if attempts < MAX_ATTEMPTS else "needs_handler"
    move(conn, claim_id, "in_progress", after)
    conn.execute(
        claims.update()
        .where(claims.c.claim_id == claim_id)
        .values(attempts=attempts, thread_id=None)
    )
    add(conn, claim_id, "error", reason, f"error-{uuid.uuid4().hex}")
    return after
