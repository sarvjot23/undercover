"""An evaluation's measures: each claim against our handlers, and the run's scores."""

from typing import Any

from sqlalchemy import Connection, RowMapping, select

from backend import runs, scoring
from backend.db import handler_decisions, judgements

# An ended evaluation never changes, so its measures are worked out once: each takes
# several round trips to Supabase, and the scoreboard and the versions list them all.
# The key names the database and the run's start, so a reseed or a test's fresh
# database never meets another's.
ENDED: dict[tuple[str, int, str], dict[str, Any]] = {}


def answer_key(conn: Connection, set_name: str) -> dict[str, dict[str, Any]]:
    """The handlers' decisions on a labelled set, by claim."""
    query = select(handler_decisions).where(handler_decisions.c.set_name == set_name)
    return {row["claim_id"]: dict(row) for row in conn.execute(query).mappings()}


def grades(conn: Connection, run_id: int) -> dict[str, dict[str, Any]]:
    """The judge's grades on an evaluation's claims, by claim."""
    query = select(judgements).where(judgements.c.run_id == run_id)
    return {row["claim_id"]: dict(row) for row in conn.execute(query).mappings()}


def work_out(conn: Connection, row: RowMapping) -> dict[str, Any]:
    """An evaluation's claims scored and its measures, from the records."""
    run = runs.describe(conn, row)
    rows = scoring.score_rows(
        run["claims"],
        answer_key(conn, row["set_name"]),
        grades(conn, row["run_id"]),
    )
    finished = run["status"] == "finished" and bool(rows)
    return {
        **run,
        "claims": rows,
        "scores": scoring.run_scores(rows, run["elapsed"]) if finished else None,
    }


def evaluation(conn: Connection, row: RowMapping) -> dict[str, Any]:
    """An evaluation with each claim scored, and its measures once it has finished.

    A stopped evaluation shows the claims it got through and no measures.
    """
    if row["status"] == "running":
        return work_out(conn, row)
    key = (str(conn.engine.url), row["run_id"], row["started_at"])
    if key not in ENDED:
        ENDED[key] = work_out(conn, row)
    return ENDED[key]
