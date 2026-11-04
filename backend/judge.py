"""The judge: Jev grades the agent's explanation against the handler's reason.

As in the Week 2 Day 5 lab. This is the only place that calls Jev, through
OpenRouter's Decisions endpoint, which is in alpha. It runs in the backend, which
holds the handlers' reasons, so the held-out set's reasons never leave it.
"""

import os
from functools import lru_cache
from typing import Any, TypedDict

from openrouter import OpenRouter
from openrouter.utils import BackoffStrategy, RetryConfig

JEV = "typesafe/jev-1.13"
DEFAULT_URL = "https://openrouter.ai"
TIMEOUT_MS = 10_000
NO_RETRIES = RetryConfig("none", BackoffStrategy(0, 0, 1.0, 0), False)

# Jev numbers the grades by their position in the list, so F is 0 and A is 3
RUBRIC = {
    "F": "different grounds from the handler's reason, or it contradicts the "
    "handler's reason",
    "C": "partly the same as the handler's reason: one of the handler's grounds or "
    "the section is missing, or it adds a ground the handler did not give",
    "B": "the same grounds and the same section of the policy wording as the "
    "handler's reason",
    "A": "the same grounds and section as the handler's reason, and clearly better "
    "expressed: clearer for the customer, with the section and the figures, "
    "shorter, and no jargon",
}
GRADES = list(RUBRIC)

QUESTIONS: dict[str, Any] = {
    "grade": {
        "type": "score",
        "instructions": "An expert claims handler decided a travel insurance claim "
        "and gave `handler.reason`, resting on `handler.reference`. Grade how well "
        "`agent.rationale` explains the same decision.",
        "criteria": [f"{letter}: {text}" for letter, text in RUBRIC.items()],
    },
    "same_grounds": {
        "type": "noul",
        "instructions": "`agent.rationale` gives the same main grounds for the "
        "decision as `handler.reason`",
    },
    "same_section": {
        "type": "noul",
        "instructions": "`agent.rationale` and `agent.section` refer to the same "
        "section of the policy wording as `handler.reference`",
    },
}


class Judgement(TypedDict):
    """The judge's answers on one claim: the grade, its letter, the two checks."""

    grade: float
    letter: str
    same_grounds: float
    same_section: float
    cost: float


# A claim the agent didn't decide has no explanation: it gets an F without a call.
UNDECIDED: Judgement = {
    "grade": 0.0,
    "letter": "F",
    "same_grounds": 0.0,
    "same_section": 0.0,
    "cost": 0.0,
}


@lru_cache
def server_url() -> str:
    """The judge's address, an origin such as https://openrouter.ai, read once."""
    return os.getenv("JUDGE_URL", DEFAULT_URL)


def ask(state: dict[str, Any]) -> Any:
    """Ask Jev the three questions about one claim: the one call to the judge.

    The client ignores an address set on it, so the address goes on the call.
    """
    client = OpenRouter(api_key=os.environ["OPENROUTER_API_KEY"])
    return client.alpha.decisions.create(
        model=JEV,
        state=state,
        questions=QUESTIONS,
        server_url=server_url(),
        retries=NO_RETRIES,
        timeout_ms=TIMEOUT_MS,
    )


def grade(handler: dict[str, Any], agent: dict[str, Any]) -> Judgement:
    """Grade the agent's explanation against the handler's reason and reference.

    The letter is the grade with the highest probability, never the score rounded.
    """
    state = {
        "handler": {
            "decision": handler["decision"],
            "reason": handler["reason"],
            "reference": handler["reference"],
        },
        "agent": {
            "decision": agent["decision"],
            "rationale": agent["reasons"],
            "section": agent["policy_section"],
        },
    }
    response = ask(state)
    answers = response.answers
    probabilities = answers["grade"].probabilities
    most_likely = max(probabilities, key=probabilities.get)
    return {
        "grade": answers["grade"].score,
        "letter": GRADES[int(most_likely)],
        "same_grounds": answers["same_grounds"].noul,
        "same_section": answers["same_section"].noul,
        "cost": response.usage.cost or 0.0,
    }
