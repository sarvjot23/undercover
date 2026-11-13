"""One piece of the agent's work at a time: a dispatch, an evaluation, or a round
while it works. On Runtime each session is a process of its own, so only the app can
keep it to one.

A start takes a lock first, a conditional write to the one row of `agent_work`, which
holds on Postgres, on SQLite and through the transaction pooler, so two starts at the
same moment can't both go through. Work the app hasn't heard about for five minutes
counts as stopped: its session ended, or the agent on the laptop restarted.
"""

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from backend import db
from backend import rounds as round_records
from backend.db import agent_work, rounds, runs

QUIET_MINUTES = 5
QUIET = "The agent stopped answering"


def ago(minutes: int) -> str:
    """The time this many minutes ago, in the format of db.now()."""
    return (datetime.fromisoformat(db.now()) - timedelta(minutes=minutes)).isoformat()


def lock(conn: Connection) -> None:
    """Hold the lock on the agent's work until this transaction ends."""
    statement = insert(agent_work).values(work_id=1, taken_at=db.now())
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=["work_id"], set_={"taken_at": statement.excluded.taken_at}
        )
    )


def stop_run(conn: Connection, run_id: int, reason: str) -> None:
    """Stop a running run with the reason; one already ended is left as it is."""
    conn.execute(
        runs.update()
        .where(runs.c.run_id == run_id, runs.c.status == "running")
        .values(status="stopped", finished_at=db.now(), stop_reason=reason)
    )


def stop_round_evaluation(conn: Connection, round_id: int, reason: str) -> None:
    """Stop the round's running evaluation with the reason, if it has one."""
    query = select(runs.c.run_id).where(
        runs.c.round_id == round_id, runs.c.status == "running"
    )
    for run_id in conn.execute(query).scalars().all():
        stop_run(conn, run_id, reason)


def stop_quiet(conn: Connection) -> None:
    """Mark stopped the work the app hasn't heard about for five minutes: a dispatch
    or an evaluation, or a working round with its running evaluation. A round's own
    evaluation is never stopped on its own: its round's word covers it."""
    cutoff = ago(QUIET_MINUTES)
    quiet_runs = select(runs.c.run_id).where(
        runs.c.status == "running",
        runs.c.round_id.is_(None),
        runs.c.heard_at < cutoff,
    )
    for run_id in conn.execute(quiet_runs).scalars().all():
        stop_run(conn, run_id, QUIET)
    quiet_rounds = select(rounds.c.round_id).where(
        rounds.c.status == "working", rounds.c.heard_at < cutoff
    )
    for round_id in conn.execute(quiet_rounds).scalars().all():
        stop_round(conn, round_id, QUIET)


def stop_round(conn: Connection, round_id: int, reason: str) -> None:
    """Stop an open round with the reason, and its running evaluation."""
    round_records.end(conn, round_id, "stopped", reason)
    stop_round_evaluation(conn, round_id, reason)


def going(conn: Connection) -> str | None:
    """What of the agent's work is going, in words, or None: a dispatch or an
    evaluation outside a round, or a round while it works."""
    run = conn.execute(
        select(runs.c.run_id, runs.c.kind).where(
            runs.c.status == "running", runs.c.round_id.is_(None)
        )
    ).first()
    if run:
        return f"{run.kind.capitalize()} {run.run_id} is running"
    round_id = conn.execute(
        select(rounds.c.round_id).where(rounds.c.status == "working")
    ).scalar()
    return f"Round {round_id} is working" if round_id else None


def begin(conn: Connection) -> None:
    """Take the lock, stop the work gone quiet, and refuse with a 409 naming what's
    going if anything is; the caller then creates its work in this transaction."""
    lock(conn)
    stop_quiet(conn)
    found = going(conn)
    if found:
        raise HTTPException(409, found)
