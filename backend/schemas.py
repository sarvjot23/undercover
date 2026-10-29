"""The request bodies of the backend's API."""

from typing import Literal

from pydantic import BaseModel, Field


class Decision(BaseModel):
    """The agent's decision on a claim."""

    decision: Literal["approve", "decline", "refer"]
    payout: float = Field(ge=0)
    reasons: str = Field(min_length=1)
    policy_section: str = Field(min_length=1)


class Payment(BaseModel):
    """A payment of a claim's approved payout."""

    amount: float


class SignOff(BaseModel):
    """A handler's sign-off on a payout over the approval limit."""

    handler_id: str


class Step(BaseModel):
    """One step of the agent's work on a claim."""

    kind: Literal["tool_call", "tool_result", "read", "answer", "error"]
    text: str


class Failure(BaseModel):
    """Why the agent's run on a claim failed."""

    reason: str
