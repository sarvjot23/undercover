"""What the improver reads: the current version, its scores and its mistakes.

From the evaluation set, the claims the current version got wrong in its latest
whole-set evaluation and the five right ones it explained least well, with our
handlers' decisions and reasons beside the agent's and the judge's grade. From
the held-out set, the scores only: no claim, decision or reason.
"""

import json
from typing import Any

from sqlalchemy import Connection, RowMapping, select

from backend import allowed, measures, spending, versions
from backend.db import claims, rounds
from backend.verdict import RULE

WEAKEST = 5


def beside_the_handler(conn: Connection, rows: list[dict[str, Any]]) -> list[Any]:
    """Each claim: the agent's answer beside the handler's, with the judge's grade."""
    key = measures.answer_key(conn, "evaluation")
    found = []
    for row in rows:
        expected = key[row["source_id"]]
        summary = conn.execute(
            select(claims.c.body).where(claims.c.claim_id == row["source_id"])
        ).scalar_one()
        found.append(
            {
                "claim_id": row["source_id"],
                "summary": json.loads(summary)["summary"],
                "agent": {
                    "decision": row["agent_decision"],
                    "payout": row["agent_payout"],
                    "rationale": row["reasons"],
                    "section": row["policy_section"],
                },
                "handler": {
                    "decision": expected["decision"],
                    "payout": expected["payout"],
                    "reason": expected["reason"],
                    "reference": expected["reference"],
                },
                "judge": {
                    "grade": row["grade"],
                    "letter": row["letter"],
                    "same_grounds": row["same_grounds"],
                    "same_section": row["same_section"],
                },
            }
        )
    return found


def mistakes(conn: Connection, version: int) -> dict[str, Any] | None:
    """The current version's wrong claims and weakest explanations, or None yet."""
    latest = versions.round_evaluations(conn, version, "evaluation")[-1:]
    if not latest:
        return None
    rows = measures.evaluation(conn, latest[0])["claims"]
    right = [row for row in rows if row["right"] and row["graded"]]
    weakest = sorted(right, key=lambda row: row["grade"])[:WEAKEST]
    return {
        "wrong": beside_the_handler(conn, [row for row in rows if not row["right"]]),
        "explained_least_well": beside_the_handler(conn, weakest),
    }


def earlier_rounds(conn: Connection, round_id: int) -> list[dict[str, Any]]:
    """The rounds before this one: what each tried, and the verdict."""
    query = (
        select(rounds)
        .where(
            rounds.c.round_id < round_id, rounds.c.status.in_(("finished", "stopped"))
        )
        .order_by(rounds.c.round_id)
    )
    found = []
    for row in conn.execute(query).mappings():
        tried = row["version_tried"]
        config = versions.find(conn, tried) if tried else None
        found.append(
            {
                "round": row["round_id"],
                "recipe_version": row["recipe_version"],
                "version_tried": tried,
                "model": config["model"] if config else None,
                "reasoning_effort": config["reasoning"] if config else None,
                "reason": row["reason"],
                "verdict": row["verdict"],
                "why": row["why"],
                "held_out_before": json.loads(row["before"]) if row["before"] else None,
                "held_out_after": json.loads(row["after"]) if row["after"] else None,
            }
        )
    return found


def view(conn: Connection, row: RowMapping) -> dict[str, Any]:
    """Everything the improver reads in a round."""
    settings = json.loads(row["settings"])
    current = versions.current(conn)
    limit = settings["round_spending_limit"]
    left = max(0.0, limit - spending.spent(conn, row["round_id"]))
    return {
        "current_version": {
            **versions.for_the_agent(current),
            "reason": current["reason"],
        },
        "scores": versions.scores(conn, current["version"]),
        "evaluation_set": mistakes(conn, current["version"]),
        "earlier_rounds": earlier_rounds(conn, row["round_id"]),
        "objectives_on_the_held_out_set": settings["objectives"],
        "noise": settings["noise"],
        "tolerance": settings["tolerance"],
        "rule": RULE,
        "spending_limit_left": round(left, 4),
        "models_allowed": allowed.models(),
    }
