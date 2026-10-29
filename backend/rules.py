"""The claims rules: where a claim stands, how it moves, and the approval limit."""

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from backend import db

APPROVAL_LIMIT = float(db.load("company.json")["payout_approval_limit"])
MAX_ATTEMPTS = 2

LOOKUPS = {
    "policy": "SELECT body FROM policies WHERE policy_id = ?",
    "customer": "SELECT body FROM customers WHERE customer_id = ?",
    "plan": "SELECT body FROM plans WHERE plan = ?",
}


def record(conn: sqlite3.Connection, kind: str, key: str) -> Any:
    """Return one stored policy, customer or plan."""
    return json.loads(conn.execute(LOOKUPS[kind], (key,)).fetchone()["body"])


def find_claim(conn: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    """Return a claim's row, or raise 404."""
    row = conn.execute(
        "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No claim {claim_id}")
    return row


def agent_working(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Whether the agent is still at work: in progress, or not yet given its answer."""
    last = conn.execute(
        "SELECT kind FROM steps WHERE claim_id = ? ORDER BY step_id DESC LIMIT 1",
        (row["claim_id"],),
    ).fetchone()
    return row["status"] == "in_progress" or (
        last is not None and last["kind"] in ("tool_call", "tool_result", "read")
    )


def decision_of(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any] | None:
    """Return the decision on a claim, if there is one."""
    row = conn.execute(
        "SELECT * FROM decisions WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    return dict(row) if row else None


def move(conn: sqlite3.Connection, claim_id: str, before: str, after: str) -> None:
    """Move a claim from one state to another, or raise 409."""
    find_claim(conn, claim_id)
    cursor = conn.execute(
        "UPDATE claims SET status = ? WHERE claim_id = ? AND status = ?",
        (after, claim_id, before),
    )
    if cursor.rowcount == 0:
        raise HTTPException(409, f"Claim {claim_id} is not {before}")


def add(conn: sqlite3.Connection, claim_id: str, kind: str, text: str) -> None:
    """Record one step of the agent's work."""
    conn.execute(
        "INSERT INTO steps (claim_id, kind, text, at) VALUES (?, ?, ?, ?)",
        (claim_id, kind, text, db.now()),
    )


def fail(conn: sqlite3.Connection, claim_id: str, reason: str) -> str:
    """Count a failed attempt on a claim in progress and say where it goes next.

    The first failure sends it back to the queue; the second leaves it for a handler.
    """
    attempts = find_claim(conn, claim_id)["attempts"] + 1
    after = "waiting" if attempts < MAX_ATTEMPTS else "needs_handler"
    move(conn, claim_id, "in_progress", after)
    conn.execute(
        "UPDATE claims SET attempts = ? WHERE claim_id = ?", (attempts, claim_id)
    )
    add(conn, claim_id, "error", reason)
    return after


def recover(conn: sqlite3.Connection) -> None:
    """Fail every claim a crash left in progress, so none stays stuck."""
    rows = conn.execute("SELECT claim_id FROM claims WHERE status = 'in_progress'")
    with conn:
        for row in rows.fetchall():
            fail(conn, row["claim_id"], "The agent stopped partway")
