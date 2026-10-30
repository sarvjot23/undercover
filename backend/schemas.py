"""The request bodies of the backend's API."""

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


class RunStart(BaseModel):
    """How many claims a queue run may work."""

    cap: int = Field(ge=1)


class Todo(BaseModel):
    """One item on the agent's to-do list for a run."""

    claim_id: str
    note: str
    status: Literal["to_do", "in_progress", "done", "left_for_handler"]


class Todos(BaseModel):
    """The agent's whole to-do list for a run."""

    todos: list[Todo]


class Summary(BaseModel):
    """The agent's summary of a run for the handlers."""

    summary: str = Field(min_length=1)
