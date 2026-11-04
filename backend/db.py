"""The UnderCover database: Supabase or SQLite, seeded from the data in data/."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    Engine,
    Float,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.pool import NullPool

DATA = Path(__file__).parent.parent / "data"
ANSWER_KEY = {"evaluation": "decisions.json", "held_out": "held_out_decisions.json"}
SCHEMA = "undercover"
MAX_CONNECTIONS = 4
# 25 claim agents share the 4 connections: a request waits for one rather than fail.
POOL_TIMEOUT = 120
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")

metadata = MetaData()


def body_table(name: str, key: str) -> Table:
    """A table of records kept as JSON under one key."""
    return Table(
        name,
        metadata,
        Column(key, Text, primary_key=True),
        Column("body", Text, nullable=False),
    )


claims = Table(
    "claims",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("thread_id", Text),
    Column("lease_owner", Text),
    Column("lease_until", Text),
    Column("evaluation_id", Integer),
    Column("source_id", Text),
)
policies = body_table("policies", "policy_id")
customers = body_table("customers", "customer_id")
plans = body_table("plans", "plan")
handlers = body_table("handlers", "handler_id")
decisions = Table(
    "decisions",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("reasons", Text, nullable=False),
    Column("policy_section", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
)
sign_offs = Table(
    "sign_offs",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("handler_id", Text, nullable=False),
    Column("signed_off_at", Text, nullable=False),
)
payments = Table(
    "payments",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("amount", Float, nullable=False),
    Column("signed_off_by", Text),
    Column("signed_off_at", Text),
    Column("paid_at", Text, nullable=False),
)
runs = Table(
    "runs",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False),
    Column("n", Integer, nullable=False),
    Column("set_name", Text),
    Column("tiny", Boolean, nullable=False),
    Column("model", Text, nullable=False),
    Column("reasoning", Text, nullable=False),
    Column("total", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
    Index(
        "one_run_at_a_time",
        "status",
        unique=True,
        sqlite_where=text("status = 'running'"),
        postgresql_where=text("status = 'running'"),
    ),
)
run_claims = Table(
    "run_claims",
    metadata,
    Column("run_id", Integer, primary_key=True),
    Column("claim_id", Text, primary_key=True),
    Column("position", Integer, nullable=False),
)
# The answer key: the held-out claims and the handlers' decisions. No claim operation
# reads these; only the scoring of an evaluation does.
held_out_claims = body_table("held_out_claims", "claim_id")
handler_decisions = Table(
    "handler_decisions",
    metadata,
    Column("set_name", Text, primary_key=True),
    Column("claim_id", Text, primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("tiny", Boolean, nullable=False),
)
usage = Table(
    "usage",
    metadata,
    Column("usage_id", Integer, primary_key=True, autoincrement=True),
    Column("claim_id", Text, nullable=False),
    Column("run_id", Integer),
    Column("model", Text, nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost", Float, nullable=False),
    Column("key", Text, nullable=False, unique=True),
)
work_sessions = Table(
    "work_sessions",
    metadata,
    Column("session_id", Integer, primary_key=True, autoincrement=True),
    Column("claim_id", Text, nullable=False),
    Column("run_id", Integer),
    Column("started", Text, nullable=False),
    Column("finished", Text, nullable=False),
    Column("seconds", Float, nullable=False),
)
steps = Table(
    "steps",
    metadata,
    Column("step_id", Integer, primary_key=True, autoincrement=True),
    Column("claim_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("key", Text, nullable=False),
    Column("at", Text, nullable=False),
    UniqueConstraint("claim_id", "key"),
)


def database_url() -> str | None:
    """Return the Supabase connection string, if it's in the environment."""
    return os.getenv("DATABASE_URL") or None


def postgres_engine(url: str) -> Engine:
    """Connect to Postgres with at most 4 connections, in our own schema."""
    engine = create_engine(
        url.replace("postgresql://", "postgresql+psycopg://", 1),
        pool_size=MAX_CONNECTIONS,
        max_overflow=0,
        pool_timeout=POOL_TIMEOUT,
        pool_recycle=1800,
        connect_args={"options": f"-c search_path={SCHEMA}", "prepare_threshold": 0},
    )

    @event.listens_for(engine, "do_connect")
    def create_schema(dialect: Any, _: Any, args: Any, params: Any) -> Any:
        """Make sure the schema exists before SQLAlchemy first asks for it."""
        conn = dialect.connect(*args, **params)
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        conn.commit()
        return conn

    return engine


@lru_cache
def build_engine(url: str | None, sqlite_path: str) -> Engine:
    """Return one engine for each database this process uses."""
    if url:
        return postgres_engine(url)
    return create_engine(
        f"sqlite:///{sqlite_path}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )


def engine() -> Engine:
    """Return the engine: Supabase if DATABASE_URL is set, otherwise a SQLite file."""
    return build_engine(database_url(), os.getenv("UNDERCOVER_DB", "undercover.db"))


def now() -> str:
    """Return the current time in UTC as ISO 8601."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def later(seconds: int) -> str:
    """Return the time this many seconds from now, in the same format."""
    return (datetime.fromisoformat(now()) + timedelta(seconds=seconds)).isoformat()


def load(name: str) -> Any:
    """Load one of the business data files in data/."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def init() -> None:
    """Create the tables and seed them from data/ if the queue is empty."""
    with engine().begin() as conn:
        metadata.create_all(conn)
        if conn.execute(select(func.count()).select_from(claims)).scalar() == 0:
            seed(conn)


def seed(conn: Connection) -> None:
    """Fill the tables from the claims queue and the insurer's records."""
    conn.execute(
        claims.insert(),
        [
            {
                "claim_id": claim["claim_id"],
                "status": "waiting",
                "body": json.dumps(claim),
                "attempts": 0,
            }
            for claim in load("claims.json")
        ],
    )
    conn.execute(policies.insert(), rows("policies.json", "policy_id"))
    conn.execute(customers.insert(), rows("customers.json", "customer_id"))
    conn.execute(handlers.insert(), rows("handlers.json", "handler_id"))
    conn.execute(
        plans.insert(),
        [
            {"plan": plan["plan"], "body": json.dumps(plan)}
            for plan in load("plans.json")["plans"]
        ],
    )
    seed_answer_key(conn)


def seed_answer_key(conn: Connection) -> None:
    """Store the held-out claims and the handlers' decisions, out of the queue."""
    conn.execute(
        held_out_claims.insert(), rows("evals/held_out_claims.json", "claim_id")
    )
    conn.execute(
        handler_decisions.insert(),
        [
            {
                "set_name": set_name,
                "claim_id": decision["claim_id"],
                "decision": decision["decision"],
                "payout": decision["payout"],
                "tiny": decision["tiny"],
            }
            for set_name, name in ANSWER_KEY.items()
            for decision in load(f"evals/{name}")
        ],
    )


def reseed() -> None:
    """Drop our tables, forget the agent's saved work and seed again from data/."""
    with engine().begin() as conn:
        metadata.drop_all(conn)
        existing = inspect(conn).get_table_names()
        for table in CHECKPOINT_TABLES:
            if table in existing:
                conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608
    init()


def rows(name: str, key: str) -> list[dict[str, str]]:
    """Return a data file's records as rows of an id and its JSON."""
    return [{key: row[key], "body": json.dumps(row)} for row in load(name)]


def warm_up() -> None:
    """Open all of Supabase's connections now: each new one takes seconds to open."""
    if database_url():
        opened = [engine().connect() for _ in range(MAX_CONNECTIONS)]
        for conn in opened:
            conn.execute(select(1))
            conn.close()


def get_db() -> Iterator[Connection]:
    """Give each request its own connection; what it doesn't commit is rolled back."""
    with engine().connect() as conn:
        yield conn


def get_single_statement_db() -> Iterator[Connection]:
    """Give a request that reads, or writes one statement, a connection in autocommit.

    Supabase is a round trip away: this saves the BEGIN and the ROLLBACK around it.
    """
    with engine().connect() as conn:
        yield conn.execution_options(isolation_level="AUTOCOMMIT")


Db = Annotated[Connection, Depends(get_db)]
SingleStatementDb = Annotated[Connection, Depends(get_single_statement_db)]
