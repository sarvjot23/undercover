"""A stand-in for the judge, so the tests never call Jev."""

from types import SimpleNamespace
from typing import Any

from backend import judge

# B is the most likely grade, and the score is 2.0.
B = {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0}


def response(
    score: float = 2.0,
    probabilities: dict[str, float] | None = None,
    grounds: float = 0.9,
    section: float = 0.8,
    cost: float = 0.0001,
) -> Any:
    """A Decisions response, shaped as the openrouter package returns it."""
    return SimpleNamespace(
        answers={
            "grade": SimpleNamespace(score=score, probabilities=probabilities or B),
            "same_grounds": SimpleNamespace(noul=grounds),
            "same_section": SimpleNamespace(noul=section),
        },
        usage=SimpleNamespace(cost=cost),
    )


def install(monkeypatch: Any, answer: Any = None) -> list[dict[str, Any]]:
    """Stand in for the judge's one call; return the states it was asked about."""
    asked: list[dict[str, Any]] = []

    def ask(state: dict[str, Any]) -> Any:
        asked.append(state)
        return answer(state) if callable(answer) else response()

    monkeypatch.setattr(judge, "ask", ask)
    return asked
