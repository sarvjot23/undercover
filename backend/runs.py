"""The rules for a queue run: its cap, its claims and when it may finish."""

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from backend import db
from backend.rules import fail, find_claim


def waiting(conn: sqlite3.Connection) -> list[str]:
    """Return the waiting claims in the order they were submitted."""
    rows = conn.execute("SELECT claim_id, body FROM claims WHERE status = 'waiting'")
    claims = sorted(
        (json.loads(r["body"])["submitted_on"], r["claim_id"]) for r in rows
    )
    return [claim_id for _, claim_id in claims]


def describe(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """Return a run with its claims in the order the agent took them."""
    claims = conn.execute(
        "SELECT claim_id FROM run_claims WHERE run_id = ? ORDER BY position",
        (row["run_id"],),
    )
    return {
        **dict(row),
        "todos": json.loads(row["todos"]),
        "claim_ids": [claim["claim_id"] for claim in claims],
    }


def find_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    """Return a run that is still going, or raise 404 or 409."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"No run {run_id}")
    if row["status"] != "running":
        raise HTTPException(409, f"Run {run_id} is {row['status']}")
    return row


def start(conn: sqlite3.Connection, cap: int) -> int:
    """Start a run on up to cap waiting claims, unless one is already going."""
    if conn.execute("SELECT 1 FROM runs WHERE status = 'running'").fetchone():
        raise HTTPException(409, "The agent is already working through the queue")
    total = min(cap, len(waiting(conn)))
    cursor = conn.execute(
        "INSERT INTO runs (cap, total, status, todos, started_at) "
        "VALUES (?, ?, 'running', '[]', ?)",
        (cap, total, db.now()),
    )
    return int(cursor.lastrowid or 0)


def take(conn: sqlite3.Connection, run_id: int, claim_id: str) -> int:
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
        "INSERT INTO run_claims VALUES (?, ?, ?)", (run_id, claim_id, len(taken) + 1)
    )
    return len(taken) + 1


def missed(conn: sqlite3.Connection, run_id: int) -> list[str]:
    """Return the waiting claims the run still has to work before it may finish."""
    run = find_run(conn, run_id)
    taken = describe(conn, run)["claim_ids"]
    queue = waiting(conn)
    retries = [claim_id for claim_id in taken if claim_id in queue]
    fresh = [claim_id for claim_id in queue if claim_id not in taken]
    return retries + fresh[: max(run["cap"] - len(taken), 0)]


def end(conn: sqlite3.Connection, run_id: int, status: str, summary: str) -> None:
    """End a run, failing any of its claims still in progress."""
    run = find_run(conn, run_id)
    for claim_id in describe(conn, run)["claim_ids"]:
        if find_claim(conn, claim_id)["status"] == "in_progress":
            fail(conn, claim_id, "The run ended while the agent was on this claim")
    conn.execute(
        "UPDATE runs SET status = ?, summary = ?, finished_at = ? WHERE run_id = ?",
        (status, summary, db.now(), run_id),
    )
