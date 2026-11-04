"""Grading an evaluation as it finishes: every claim at once, all within 20 seconds.

Each call to the judge times out after 10 seconds with no retries, and every claim
is graded in parallel, so finishing stays well within the agent's wait. A claim
the agent didn't decide gets an F without a call; a claim the judge couldn't grade
is left ungraded, and out of the average. With MODEL_NAME set, as on the free
route, the judge isn't called at all.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import Connection, RowMapping

from backend import judge, measures, runs
from backend.db import judgements
from backend.judge import Judgement

AT_ONCE = 25
# Every row names every column: a bulk insert takes its columns from the first.
UNGRADED: dict[str, Any] = {
    "grade": None,
    "letter": None,
    "same_grounds": None,
    "same_section": None,
    "cost": None,
}


def tasks(conn: Connection, row: RowMapping) -> list[dict[str, Any]]:
    """What the judge needs for each of an evaluation's claims."""
    key = measures.answer_key(conn, row["set_name"])
    return [
        {
            "claim_id": entry["claim_id"],
            "handler": key[entry["source_id"]],
            "agent": entry if entry["decision"] else None,
        }
        for entry in runs.claim_entries(conn, row["run_id"])
    ]


def grade_one(task: dict[str, Any]) -> Judgement | None:
    """The judge's grade on one claim, an F if it wasn't decided, or None."""
    if task["agent"] is None:
        return judge.UNDECIDED
    if os.getenv("MODEL_NAME"):
        return None
    try:
        return judge.grade(task["handler"], task["agent"])
    except Exception:
        # A timeout or a refusal: the claim shows as not graded.
        return None


def grade_all(work: list[dict[str, Any]]) -> dict[str, Judgement | None]:
    """Grade every claim in parallel."""
    if not work:
        return {}
    with ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
        graded = pool.map(grade_one, work)
        return {
            task["claim_id"]: found for task, found in zip(work, graded, strict=True)
        }


def row(run_id: int, claim_id: str, found: Judgement | None) -> dict[str, Any]:
    """One claim's row of grades, with no grade if it wasn't graded."""
    values: dict[str, Any] = dict(found) if found else UNGRADED
    return {"run_id": run_id, "claim_id": claim_id, "graded": bool(found), **values}


def save(conn: Connection, run_id: int, graded: dict[str, Judgement | None]) -> None:
    """Store the grades: a claim not graded keeps a row with no grade."""
    if graded:
        conn.execute(
            judgements.insert(),
            [row(run_id, claim_id, found) for claim_id, found in graded.items()],
        )
