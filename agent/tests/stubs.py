"""Stand-ins for the model and the backend, so tests never call a model."""

import itertools

from fastapi.testclient import TestClient
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import client
from agent.screening import Screening
from backend.api import app as backend_app

ids = itertools.count()


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


class BrokenModel(StubModel):
    """A chat model whose provider is down."""

    def _generate(self, *args, **kwargs):
        raise RuntimeError("model down")


class FlakyModel(StubModel):
    """A chat model whose provider fails once, then answers."""

    failed: bool = False

    def _generate(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise RuntimeError("provider hiccup")
        return super()._generate(*args, **kwargs)


class RateLimitedModel(StubModel):
    """A chat model that hits a rate limit on these calls, and answers on the others."""

    limited: list[int]
    calls: int = 0

    def _generate(self, *args, **kwargs):
        self.calls += 1
        if self.calls in self.limited:
            raise ModelRateLimitError("429 Too Many Requests")
        return super()._generate(*args, **kwargs)


class Stopped(BaseException):
    """The process being killed: nothing in the agent catches this."""


class StoppedModel(StubModel):
    """A chat model that plays its replies; the process is killed on the next call."""

    def _generate(self, *args, **kwargs):
        try:
            return super()._generate(*args, **kwargs)
        except StopIteration:
            raise Stopped from None


class Backend(TestClient):
    """The backend as the agent sees it: already running, so no startup per call."""

    def __init__(self, app, **kwargs):
        super().__init__(app, headers=client.key_header(), **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def call(name, **args):
    """A model reply that calls one tool."""
    tool_call = {"name": name, "args": args, "id": f"call-{next(ids)}"}
    return AIMessage(content="", tool_calls=[tool_call])


def script(*replies):
    """A stub model that plays these replies in order."""
    return StubModel(messages=iter(replies))


def screened(found, reason="Nothing in the claim instructs its handler.", usage=None):
    """One answer from the check's model, as with_structured_output gives it."""
    metadata = {"model_name": "stub-checker"}
    if usage:
        metadata["token_usage"] = usage
    raw = AIMessage(content="", id=f"check-{next(ids)}", response_metadata=metadata)
    parsed = (
        None if found is None else Screening(reason=reason, instructions_found=found)
    )
    return {"raw": raw, "parsed": parsed, "parsing_error": None}


class StubChecker:
    """The security check's model: scripted answers, and a pass once they run out.

    An answer of None found is one that can't be read; an exception is raised.
    """

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def with_structured_output(self, schema, include_raw):
        assert schema is Screening
        assert include_raw
        return self

    def invoke(self, messages):
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else screened(False)
        if isinstance(answer, Exception):
            raise answer
        return answer


FIELDS = {
    "reasons": "The wording settles it. The documents support it.",
    "policy_section": "3. Trip Delay",
}


def deductible(claim_id):
    """The deductible of the claim's plan."""
    with Backend(backend_app) as backend:
        return backend.get(f"/api/claims/{claim_id}").json()["plan"]["deductible"]


def decide(decision, payout, claim_id="CLM-1001", **fields):
    """The model's replies that record a decision, as the claim agent would.

    An approval works out its payout first, so a calculation is on file: one expense
    under emergency medical for the payout plus the plan's deductible.
    """
    record = call(
        "record_decision", decision=decision, payout=payout, **{**FIELDS, **fields}
    )
    if decision != "approve":
        return [record]
    line = {
        "description": "Covered costs",
        "amount": payout + deductible(claim_id),
        "quantity": 1,
        "kind": "expense",
        "nights": 0,
        "hours": 0,
    }
    calculation = call(
        "calculate_payout",
        benefit="emergency_medical",
        lines=[line],
        paid_by_others=0,
    )
    return [calculation, record]
