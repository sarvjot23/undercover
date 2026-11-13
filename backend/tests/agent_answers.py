"""The agent's answers, for tests that stand in for it."""

from backend.agent_service import Answer

ACCEPTED = Answer("accepted", "", {"accepted": True})


def refused_with(reason: str) -> Answer:
    """The agent's refusal, with its reason."""
    return Answer("refused", reason, {"refused": reason})


# The body of a stop or a halt the agent sends, saying why.
STOPPED = {"reason": "Stopped by a test"}
