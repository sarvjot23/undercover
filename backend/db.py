"""The UnderCover database: SQLite, seeded from the business data in data/."""

import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent.parent / "data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (policy_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers (customer_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (plan TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handlers (handler_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
    claim_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL,
    payout REAL NOT NULL,
    reasons TEXT NOT NULL,
    policy_section TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    claim_id TEXT PRIMARY KEY,
    amount REAL NOT NULL,
    signed_off_by TEXT,
    paid_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    at TEXT NOT NULL
);
"""


def path() -> str:
    """Return the database file, from UNDERCOVER_DB or undercover.db."""
    return os.getenv("UNDERCOVER_DB", "undercover.db")


def now() -> str:
    """Return the current time in UTC as ISO 8601."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def load(name: str) -> Any:
    """Load one of the business data files in data/."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def connect() -> sqlite3.Connection:
    """Open a connection to the database."""
    conn = sqlite3.connect(path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Create the tables and seed them from data/ if the queue is empty."""
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0:
            seed(conn)
    conn.close()


def seed(conn: sqlite3.Connection) -> None:
    """Fill the tables from the claims queue and the insurer's records."""
    for claim in load("claims.json"):
        conn.execute(
            "INSERT INTO claims VALUES (?, 'waiting', ?)",
            (claim["claim_id"], json.dumps(claim)),
        )
    conn.executemany(
        "INSERT INTO policies VALUES (?, ?)", rows("policies.json", "policy_id")
    )
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?)", rows("customers.json", "customer_id")
    )
    conn.executemany(
        "INSERT INTO handlers VALUES (?, ?)", rows("handlers.json", "handler_id")
    )
    plans = load("plans.json")["plans"]
    conn.executemany(
        "INSERT INTO plans VALUES (?, ?)", [(p["plan"], json.dumps(p)) for p in plans]
    )


def rows(name: str, key: str) -> list[tuple[str, str]]:
    """Return a data file's records as (id, JSON) pairs."""
    return [(row[key], json.dumps(row)) for row in load(name)]


def get_db() -> Iterator[sqlite3.Connection]:
    """Give each request its own connection."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
