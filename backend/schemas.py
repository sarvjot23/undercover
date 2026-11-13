"""The request bodies of the backend's API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from backend.payout import Benefit, Line

NOTE_LENGTH = 1000


class Decision(BaseModel):
    """The agent's decision on a claim, with who or what made it.

    Section 14's checks are our own, in backend/decision_record.py, so a refusal
    names the section and what's missing.
    """

    decision: Literal["approve", "decline", "refer"]
    payout: float
    reasons: str
    policy_section: str
    decided_by: str


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

    kind: Literal[
        "check",
        "tool_call",
        "tool_result",
        "lookup",
        "memory_search",
        "memory_save",
        "refusal",
        "send_back",
        "answer",
        "error",
    ]
    text: str
    key: str
    # A lookup's detail is what was looked up and the files it came from, each with
    # its source; a refusal's is who refused, and a send back's who sent it back.
    # Other kinds have none.
    detail: dict[str, Any] | None


class Hold(BaseModel):
    """Why the Gateway refused to pay an approved claim."""

    reason: str = Field(min_length=1)


class SendBack(BaseModel):
    """A senior handler's note on what the agent should look at again."""

    note: str = Field(max_length=NOTE_LENGTH)

    @field_validator("note")
    @classmethod
    def not_blank(cls, note: str) -> str:
        """A note of only spaces says nothing."""
        if not note.strip():
            raise ValueError("A send back needs a note saying what to look at again")
        return note.strip()


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
    """A dispatch or an evaluation, as the app creates it, or a round's evaluation,
    as the agent creates it.

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


class StopReason(BaseModel):
    """Why the agent stopped its work on a run or a round."""

    reason: str = Field(min_length=1)


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
