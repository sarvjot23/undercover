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


class ClaimStart(BaseModel):
    """The thread the agent works a claim on."""

    thread_id: str


class Lease(BaseModel):
    """The worker taking, renewing or giving up a lease."""

    worker: str


class Step(BaseModel):
    """One step of the agent's work on a claim."""

    kind: Literal["check", "tool_call", "tool_result", "read", "answer", "error"]
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
    """A dispatch or an evaluation, as the agent's service starts it.

    With no version it uses the current one; a round's evaluation names its own.
    """

    kind: Literal["dispatch", "evaluation"]
    n: int = Field(ge=1, le=MAX_AGENTS)
    set_name: SetName | None
    tiny: bool
    version: int | None
    round_id: int | None


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


class RoundStart(BaseModel):
    """The handler who started a round, as the agent's service passes it on."""

    handler_id: str


class RoundProgress(BaseModel):
    """Where a working round has got to, such as evaluations, 2 of 3."""

    stage: Literal["first_evaluations", "improving", "evaluations"]
    progress: str | None


class ChangeProposal(BaseModel):
    """A new version of the claim agent's configuration, proposed by the improver."""

    instructions: str = Field(min_length=1)
    model: str
    reasoning: str
    reason: str = Field(min_length=1)


class RecipeProposal(BaseModel):
    """A new version of the improver's recipe."""

    recipe: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RoundDecision(BaseModel):
    """A handler's approval or rejection of a proposal; a rejection says why."""

    decision: Literal["approve", "reject"]
    message: str


class RecordedDecision(RoundDecision):
    """A decision on a proposal, with the handler, as the agent's service records it."""

    handler_id: str


class Verdict(BaseModel):
    """Judge the version tried, or roll it back as one the round can't afford."""

    unaffordable: bool


class RoundUsage(BaseModel):
    """The tokens and cost of one of the improver's model replies."""

    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float = Field(ge=0)
    key: str
