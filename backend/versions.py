"""The claim agent's configuration in versions, and the improver's recipe.

A version's scores are the averages of the whole-set evaluations that rounds ran on
it, one set at a time. An evaluation started on the Scoreboard doesn't count, and
nor does an evaluation of the tiny claims.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, func, select

from backend import measures
from backend.db import config_versions, recipe_versions, runs

SETS = ("evaluation", "held_out")
FOR_THE_AGENT = ("version", "instructions", "model", "reasoning")


def current(conn: Connection) -> RowMapping:
    """The current version of the configuration."""
    query = select(config_versions).where(config_versions.c.current.is_(True))
    return conn.execute(query).mappings().one()


def find(conn: Connection, version: int) -> RowMapping:
    """A version of the configuration, or 404."""
    query = select(config_versions).where(config_versions.c.version == version)
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"No version {version}")
    return row


def for_the_agent(row: RowMapping) -> dict[str, Any]:
    """What the claim agent works from: instructions, model and effort, no scores."""
    return {name: row[name] for name in FOR_THE_AGENT}


def average(scores: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The average of each measure over some runs, or None for no runs.

    A measure missing from a run, such as a grade with nothing graded, is averaged
    over the runs that have it, and is None if none do.
    """
    if not scores:
        return None
    averaged: dict[str, Any] = {"runs": len(scores)}
    for name in scores[0]:
        values = [found[name] for found in scores if found[name] is not None]
        averaged[name] = sum(values) / len(values) if values else None
    return averaged


def round_evaluations(conn: Connection, version: int, set_name: str) -> list[Any]:
    """The finished whole-set evaluations that rounds ran on a version, oldest first."""
    query = (
        select(runs)
        .where(
            runs.c.kind == "evaluation",
            runs.c.version == version,
            runs.c.set_name == set_name,
            runs.c.round_id.is_not(None),
            runs.c.tiny.is_(False),
            runs.c.status == "finished",
        )
        .order_by(runs.c.run_id)
    )
    return list(conn.execute(query).mappings())


def scores(conn: Connection, version: int) -> dict[str, dict[str, Any] | None]:
    """A version's scores on each set, from the whole-set evaluations of rounds."""
    found: dict[str, dict[str, Any] | None] = {}
    for set_name in SETS:
        evaluated = [
            measures.evaluation(conn, row)["scores"]
            for row in round_evaluations(conn, version, set_name)
        ]
        found[set_name] = average([score for score in evaluated if score])
    return found


def changed(before: RowMapping | None, row: RowMapping) -> list[str]:
    """What a version changed from the one before."""
    if before is None:
        return []
    names = {
        "instructions": "instructions",
        "model": "model",
        "reasoning": "reasoning effort",
    }
    return [label for name, label in names.items() if before[name] != row[name]]


def listing(conn: Connection) -> list[dict[str, Any]]:
    """Every version, newest first, with what it changed and its scores."""
    rows = list(
        conn.execute(select(config_versions).order_by(config_versions.c.version))
    )
    found = []
    before = None
    for row in (row._mapping for row in rows):
        found.append(
            {
                **row,
                "changed": changed(before, row),
                "scores": scores(conn, row["version"]),
            }
        )
        before = row
    return found[::-1]


def next_number(conn: Connection, table: Any) -> int:
    """The number the next version of a configuration or recipe gets."""
    return int(conn.execute(select(func.max(table.c.version))).scalar() or 0) + 1


def latest_recipe(conn: Connection) -> RowMapping:
    """The recipe the improver follows: its latest version."""
    query = select(recipe_versions).order_by(recipe_versions.c.version.desc())
    return conn.execute(query.limit(1)).mappings().one()


def find_recipe(conn: Connection, version: int) -> RowMapping:
    """A version of the recipe, or 404."""
    query = select(recipe_versions).where(recipe_versions.c.version == version)
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"No recipe version {version}")
    return row
