"""Scoring an evaluation against the handlers' decisions, as in the Week 2 Day 4 lab."""

from typing import Any

WRONGFUL_DECLINE = 1500
NEEDLESS_REFERRAL = 50
# A claim the agent didn't decide counts as a referral with no payout.
UNDECIDED = {"decision": "refer", "payout": 0.0}
NOT_GRADED = {
    "graded": False,
    "grade": None,
    "letter": None,
    "same_grounds": None,
    "same_section": None,
    "cost": 0.0,
}


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


def run_scores(rows: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    """The scores for a whole run: quality, cost and time.

    The grade is the judge's average over the claims it graded, or None if it
    graded none. The judge's cost is kept apart from the claim agent's.
    """
    grades = [row["grade"] for row in rows if row["graded"]]
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
        "grade": mean(grades) if grades else None,
        "judge_cost": sum(row["judge_cost"] for row in rows),
    }


def judged(found: dict[str, Any] | None) -> dict[str, Any]:
    """A claim's grade and checks, with the judge's cost apart from the agent's."""
    found = found if found and found["graded"] else NOT_GRADED
    return {
        "graded": found["graded"],
        "grade": found["grade"],
        "letter": found["letter"],
        "same_grounds": found["same_grounds"],
        "same_section": found["same_section"],
        "judge_cost": found["cost"] or 0.0,
    }


def score_rows(
    entries: list[dict[str, Any]],
    key: dict[str, dict[str, Any]],
    grades: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Each claim of an evaluation: the agent's answer beside the handler's, graded."""
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
                **judged(grades.get(entry["claim_id"])),
            }
        )
    return rows
