"""Scoring an evaluation against the handlers' decisions, as in the Week 2 Day 4 lab."""

from typing import Any

WRONGFUL_DECLINE = 1500
NEEDLESS_REFERRAL = 50
# A claim the agent didn't decide counts as a referral with no payout.
UNDECIDED = {"decision": "refer", "payout": 0.0}


def is_right(answer: dict[str, Any], expected: dict[str, Any]) -> bool:
    """True when the decision matches the handler's and the payout is within $1."""
    return (
        answer["decision"] == expected["decision"]
        and abs(answer["payout"] - expected["payout"]) <= 1
    )


def mistake_cost(answer: dict[str, Any], expected: dict[str, Any]) -> float:
    """What the agent's answer costs UnderCover, against the handler's decision."""
    if answer["decision"] == expected["decision"]:
        if answer["decision"] == "approve":
            return abs(answer["payout"] - expected["payout"])
        return 0.0
    if answer["decision"] == "decline":
        return WRONGFUL_DECLINE
    if answer["decision"] == "approve":
        return answer["payout"]
    return NEEDLESS_REFERRAL


def mean(values: list[float]) -> float:
    """The average, or 0 for no values."""
    return sum(values) / len(values) if values else 0.0


def run_scores(rows: list[dict[str, Any]], seconds: float) -> dict[str, float]:
    """The scores for a whole run: quality, cost and time."""
    return {
        "decision_accuracy": mean(
            [row["agent_decision"] == row["handler_decision"] for row in rows]
        ),
        "accuracy": mean([row["right"] for row in rows]),
        "cost_of_mistakes": sum(row["mistake_cost"] for row in rows),
        "straight_through": mean([row["agent_decision"] != "refer" for row in rows]),
        "cost": sum(row["cost"] for row in rows),
        "cost_per_claim": mean([row["cost"] for row in rows]),
        "seconds_per_claim": mean([row["seconds"] for row in rows]),
        "seconds": seconds,
    }


def score_rows(
    entries: list[dict[str, Any]], key: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each claim of an evaluation: the agent's answer beside the handler's."""
    rows = []
    for entry in entries:
        expected = key[entry["source_id"]]
        answer = (
            {"decision": entry["decision"], "payout": entry["payout"]}
            if entry["decision"]
            else UNDECIDED
        )
        rows.append(
            {
                **entry,
                "handler_decision": expected["decision"],
                "handler_payout": expected["payout"],
                "agent_decision": answer["decision"],
                "agent_payout": answer["payout"],
                "right": is_right(answer, expected),
                "mistake_cost": mistake_cost(answer, expected),
            }
        )
    return rows
