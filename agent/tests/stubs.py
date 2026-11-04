"""Stand-ins for the model and the backend, so tests never call a model."""

import itertools

from fastapi.testclient import TestClient
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

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
