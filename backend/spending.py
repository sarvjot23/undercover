"""A round's spending limit: what it has spent, and what an evaluation might cost.

Spent is the improver's own model calls, and in all the round's evaluations, its
first ones included, the claim agents' calls and the judge's. An evaluation's
estimate is its claims times the highest cost per claim seen so far for its model.
For a model with no runs yet, it is the current model's, scaled by the larger of
the ratios of their input and output prices.
"""

from typing import Any

from sqlalchemy import Connection, func, select

from backend import allowed
from backend.db import handler_decisions, judgements, runs, usage


def total(conn: Connection, query: Any) -> float:
    """A sum of costs, or 0 for none."""
    return float(conn.execute(query).scalar() or 0.0)


def spent(conn: Connection, round_id: int) -> float:
    """What a round has spent: the improver, the claim agents and the judge."""
    round_runs = select(runs.c.run_id).where(runs.c.round_id == round_id)
    improver = select(func.sum(usage.c.cost)).where(usage.c.round_id == round_id)
    agents = select(func.sum(usage.c.cost)).where(usage.c.run_id.in_(round_runs))
    judge = select(func.sum(judgements.c.cost)).where(
        judgements.c.run_id.in_(round_runs)
    )
    return total(conn, improver) + total(conn, agents) + total(conn, judge)


def highest_per_claim(conn: Connection, model: str) -> float | None:
    """The highest cost per claim of any finished evaluation on a model, or None."""
    query = select(runs.c.run_id, runs.c.total).where(
        runs.c.kind == "evaluation",
        runs.c.status == "finished",
        runs.c.model == model,
        runs.c.total > 0,
    )
    costs = [
        total(conn, select(func.sum(usage.c.cost)).where(usage.c.run_id == run_id))
        / claims
        for run_id, claims in conn.execute(query).all()
    ]
    return max(costs) if costs else None


def price_ratio(model: str, current: str) -> float:
    """How much dearer a model is than the current one: the larger price ratio."""
    new, old = allowed.find(model), allowed.find(current)
    if not new or not old or not old["input_price"] or not old["output_price"]:
        return 1.0
    return max(
        new["input_price"] / old["input_price"],
        new["output_price"] / old["output_price"],
    )


def per_claim(conn: Connection, model: str, current: str) -> float:
    """The estimated cost of a claim on a model."""
    seen = highest_per_claim(conn, model)
    if seen is not None:
        return seen
    return (highest_per_claim(conn, current) or 0.0) * price_ratio(model, current)


def whole_set_claims(conn: Connection) -> int:
    """The claims in a version's evaluations: once the evaluation set, twice the
    held-out set."""
    sizes = dict(
        conn.execute(
            select(handler_decisions.c.set_name, func.count()).group_by(
                handler_decisions.c.set_name
            )
        ).all()
    )
    return sizes.get("evaluation", 0) + 2 * sizes.get("held_out", 0)
