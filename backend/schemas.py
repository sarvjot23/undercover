"""The request bodies of the backend's API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.payout import Benefit, Line


class Decision(BaseModel):
    """The agent's decision on a claim."""

    decision: Literal["approve", "decline", "refer"]
    payout: float = Field(ge=0)
    reasons: str = Field(min_length=1)
    policy_section: str = Field(min_length=1)


class Payment(BaseModel):
    """A payment of a claim's approved payout."""

    amount: float


class PayoutRequest(BaseModel):
    """What the payout rules need: the benefit, the covered lines, what others paid."""

    benefit: Benefit
    lines: list[Line]
    paid_by_others: float = Field(ge=0)


class SignOff(BaseModel):
    """A handler's sign-off on a payout over the approval limit."""

    handler_id: str


class ClaimStart(BaseModel):
    """The thread the agent works a claim on."""

    thread_id: str


class Lease(BaseModel):
    """The worker taking, renewing or giving up a lease."""

    worker: str


class Step(BaseModel):
    """One step of the agent's work on a claim."""

    kind: Literal["tool_call", "tool_result", "read", "answer", "error"]
    text: str
    key: str


class Failure(BaseModel):
    """Why the agent's run on a claim failed."""

    reason: str


SetName = Literal["evaluation", "held_out"]
MAX_AGENTS = 25


class DispatchStart(BaseModel):
    """How many claim agents a dispatch works with at once."""

    n: int = Field(ge=1, le=MAX_AGENTS)


class EvaluationStart(BaseModel):
    """The labelled set to evaluate, whole or its tiny claims, and N."""

    set_name: SetName
    tiny: bool
    n: int = Field(ge=1, le=MAX_AGENTS)


class RunRecord(BaseModel):
    """A dispatch or an evaluation, as the agent's service starts it."""

    kind: Literal["dispatch", "evaluation"]
    n: int = Field(ge=1, le=MAX_AGENTS)
    set_name: SetName | None
    tiny: bool
    model: str
    reasoning: str


class Usage(BaseModel):
    """The tokens and cost of one model reply, as OpenRouter reports them."""

    run_id: int | None
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float = Field(ge=0)
    key: str


class WorkSession(BaseModel):
    """A spell of the agent's work on a claim, which ends when its graph stops."""

    run_id: int | None
    started: datetime
    finished: datetime
