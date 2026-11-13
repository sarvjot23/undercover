"""The UnderCover database: Supabase or SQLite, seeded from the data in data/ and
data governance's plans and documents in context/, which only seeding reads."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends
from sqlalchemy import (
    JSON,
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
CONTEXT = Path(__file__).parent.parent / "context"
DOCUMENTS = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}
INSTRUCTIONS = Path(__file__).parent / "instructions"
DEFAULT_MODEL = "openai/gpt-6-luna"
DEFAULT_REASONING = "low"
ANSWER_KEY = {"evaluation": "decisions.json", "held_out": "held_out_decisions.json"}
SCHEMA = "undercover"
MAX_CONNECTIONS = 4
SECURITY_CLAIMS = "security/claims.json"
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
# The policy wording and the claims manual, with the version and source of each.
documents = Table(
    "documents",
    metadata,
    Column("document", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("version", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("text", Text, nullable=False),
)
handlers = Table(
    "handlers",
    metadata,
    Column("handler_id", Text, primary_key=True),
    Column("email", Text, nullable=False, unique=True),
    Column("body", Text, nullable=False),
)
decisions = Table(
    "decisions",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("reasons", Text, nullable=False),
    Column("policy_section", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
    # The limit the decision was made under: a new limit applies to later decisions.
    Column("approval_limit", Float, nullable=False),
    # Why the Gateway refused the payment, when it did: the claim then waits for a
    # handler's sign-off, as an approval over the limit does.
    Column("payment_refused", Text),
    # Section 14's record: the calculation behind an approval (none for a decline or
    # a referral), who or what made the decision, and the manual's version (section 13).
    Column("calculation", JSON),
    Column("decided_by", Text, nullable=False),
    Column("manual_version", Text, nullable=False),
)
# The latest payout calculation for each claim and attempt: an approval must match it.
calculations = Table(
    "calculations",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("attempt", Integer, primary_key=True),
    Column("calculation", JSON, nullable=False),
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
    Column("version", Integer, nullable=False),
    Column("round_id", Integer),
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
    Column("reason", Text, nullable=False),
    Column("reference", Text, nullable=False),
)
# The judge's grade on each claim of an evaluation, kept apart from the answers.
judgements = Table(
    "judgements",
    metadata,
    Column("run_id", Integer, primary_key=True),
    Column("claim_id", Text, primary_key=True),
    Column("graded", Boolean, nullable=False),
    Column("grade", Float),
    Column("letter", Text),
    Column("same_grounds", Float),
    Column("same_section", Float),
    Column("cost", Float),
)
usage = Table(
    "usage",
    metadata,
    Column("usage_id", Integer, primary_key=True, autoincrement=True),
    # A claim agent's reply, or the improver's with its round and no claim.
    Column("claim_id", Text),
    Column("run_id", Integer),
    Column("round_id", Integer),
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
    # What a lookup looked up and where it came from, or who refused; else empty.
    Column("detail", JSON),
    UniqueConstraint("claim_id", "key"),
)
# The claim agent's configuration, in versions: exactly one is current.
config_versions = Table(
    "config_versions",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("instructions", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("reasoning", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("proposed_by", Text, nullable=False),
    Column("approved_by", Text),
    Column("approved_at", Text, nullable=False),
    Column("current", Boolean, nullable=False),
)
# The improver's recipe, in versions: the latest is the one it follows.
recipe_versions = Table(
    "recipe_versions",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("recipe", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("proposed_by", Text, nullable=False),
    Column("approved_by", Text),
    Column("approved_at", Text, nullable=False),
)
# A round of improvement: its own copy of the settings, where it has got to, and
# the proposal waiting for a handler, if one is.
rounds = Table(
    "rounds",
    metadata,
    Column("round_id", Integer, primary_key=True, autoincrement=True),
    Column("thread_id", Text),
    Column("recipe_version", Integer, nullable=False),
    Column("settings", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("stage", Text, nullable=False),
    Column("progress", Text),
    Column("proposal", Text),
    Column("version_before", Integer, nullable=False),
    Column("version_tried", Integer),
    Column("reason", Text),
    Column("before", Text),
    Column("after", Text),
    Column("verdict", Text),
    Column("why", Text),
    Column("started_by", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
)
# Each approval or rejection of an improver's proposal, by whom and why.
round_events = Table(
    "round_events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("round_id", Integer, nullable=False),
    Column("decision", Text, nullable=False),
    Column("proposal", Text, nullable=False),
    Column("handler_id", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("at", Text, nullable=False),
)
settings = Table(
    "settings",
    metadata,
    Column("name", Text, primary_key=True),
    Column("value", Float, nullable=False),
)
setting_changes = Table(
    "setting_changes",
    metadata,
    Column("change_id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("before", Float, nullable=False),
    Column("after", Float, nullable=False),
    Column("handler_id", Text, nullable=False),
    Column("changed_at", Text, nullable=False),
)


def database_url() -> str | None:
    """Return the Supabase connection string, if it's in the environment."""
    return os.getenv("DATABASE_URL") or None


def on_lambda() -> bool:
    """Whether the backend runs on AWS Lambda, which sets this for every function."""
    return bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def postgres_engine(url: str) -> Engine:
    """Connect to Postgres with at most 4 connections, in our own schema.

    On Lambda each copy of the function opens a connection for each request and
    keeps none, through the transaction pooler, which can't prepare statements.
    """
    driver_url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    options = f"-c search_path={SCHEMA}"
    if on_lambda():
        engine = create_engine(
            driver_url,
            poolclass=NullPool,
            connect_args={"options": options, "prepare_threshold": None},
        )
    else:
        engine = create_engine(
            driver_url,
            pool_size=MAX_CONNECTIONS,
            max_overflow=0,
            pool_timeout=POOL_TIMEOUT,
            pool_recycle=1800,
            connect_args={"options": options, "prepare_threshold": 0},
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
    """Fill the tables from the claims queue and the insurer's records.

    The security team's claim, CLM-1901, joins the queue with its policy and its
    customer, but not its handler's decision, so it stays out of the evaluations.
    """
    conn.execute(
        claims.insert(),
        [
            {
                "claim_id": claim["claim_id"],
                "status": "waiting",
                "body": json.dumps(claim),
                "attempts": 0,
            }
            for claim in load("claims.json") + load(SECURITY_CLAIMS)
        ],
    )
    for name in ("policies.json", "security/policies.json"):
        conn.execute(policies.insert(), rows(name, "policy_id"))
    for name in ("customers.json", "security/customers.json"):
        conn.execute(customers.insert(), rows(name, "customer_id"))
    conn.execute(
        handlers.insert(),
        [
            {
                "handler_id": handler["handler_id"],
                "email": handler["email"],
                "body": json.dumps(handler),
            }
            for handler in load("handlers.json")
        ],
    )
    seed_plans(conn)
    seed_documents(conn)
    seed_answer_key(conn)
    seed_versions(conn)
    seed_settings(conn)


def seed_plans(conn: Connection) -> None:
    """Each plan from policy administration, with what every plan shares: the
    benefits the deductible applies to and the add-ons."""
    found = yaml.safe_load((CONTEXT / "plans.yaml").read_text(encoding="utf-8"))
    shared = {
        "deductible_applies_to": found["deductible_applies_to"],
        "add_ons": found["add_ons"],
    }
    conn.execute(
        plans.insert(),
        [
            {"plan": plan["plan"], "body": json.dumps({**plan, **shared})}
            for plan in found["plans"]
        ],
    )


def seed_documents(conn: Connection) -> None:
    """The wording and the manual, each with the version and source in its front
    matter, which is left out of its text."""
    for document, name in DOCUMENTS.items():
        whole = (CONTEXT / f"{document}.md").read_text(encoding="utf-8")
        _, front, text = whole.split("---\n", 2)
        meta = yaml.safe_load(front)
        conn.execute(
            documents.insert().values(
                document=document,
                name=name,
                version=meta["version"],
                source=json.dumps(meta["source"]),
                text=text.strip(),
            )
        )


def seed_versions(conn: Connection) -> None:
    """Version 1 of the claim agent's configuration and of the improver's recipe.

    With MODEL_NAME set, as on the free route, version 1 uses that model.
    """
    free = os.getenv("MODEL_NAME")
    seeded = {"proposed_by": "seed", "approved_by": None, "approved_at": now()}
    conn.execute(
        config_versions.insert().values(
            version=1,
            instructions=(INSTRUCTIONS / "claim.md").read_text(encoding="utf-8"),
            model=free or DEFAULT_MODEL,
            reasoning="default" if free else DEFAULT_REASONING,
            reason="The claim agent as it was before the improver.",
            current=True,
            **seeded,
        )
    )
    conn.execute(
        recipe_versions.insert().values(
            version=1,
            recipe=(INSTRUCTIONS / "recipe.md").read_text(encoding="utf-8"),
            reason="The first recipe, from our team's lab.",
            **seeded,
        )
    )


def flatten(values: dict[str, Any], prefix: str = "") -> dict[str, float]:
    """Settings as names and numbers, such as noise.accuracy."""
    flat: dict[str, float] = {}
    for name, value in values.items():
        if isinstance(value, dict):
            flat |= flatten(value, f"{prefix}{name}.")
        else:
            flat[f"{prefix}{name}"] = float(value)
    return flat


def seed_settings(conn: Connection) -> None:
    """The approval limit from company.json, the other settings from settings.json."""
    values = {
        "approval_limit": load("company.json")["payout_approval_limit"],
        **load("settings.json"),
    }
    conn.execute(
        settings.insert(),
        [{"name": name, "value": value} for name, value in flatten(values).items()],
    )


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
                "reason": decision["reason"],
                "reference": decision["reference"],
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
