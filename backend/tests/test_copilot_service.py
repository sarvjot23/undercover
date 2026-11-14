import io
import json

import httpx
import pytest
from botocore.exceptions import ClientError

from backend import copilot_service

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/undercover_copilot-x"
SESSION = "conv-0123456789abcdef0123456789abcdef"
PAYLOAD = {"operation": "turn", "conversation_id": SESSION}


def conflict():
    return ClientError(
        {"Error": {"Code": "ConflictException", "Message": "Session is starting"}},
        "InvokeAgentRuntime",
    )


class Runtime:
    """A stand-in for boto3's bedrock-agentcore client."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def invoke_agent_runtime(self, **call):
        self.calls.append(call)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"response": io.BytesIO(json.dumps(answer).encode())}


@pytest.fixture
def runtime(monkeypatch):
    stand_in = Runtime([])
    monkeypatch.setenv("UNDERCOVER_COPILOT_RUNTIME", ARN)
    monkeypatch.setattr(copilot_service.boto3, "client", lambda *a, **k: stand_in)
    monkeypatch.setattr(copilot_service, "CONFLICT_WAIT", 0)
    return stand_in


def test_a_turn_goes_to_the_conversations_own_session(runtime):
    runtime.answers.append({"accepted": True})
    answer = copilot_service.send(SESSION, PAYLOAD)
    assert answer.outcome == "accepted"
    [call] = runtime.calls
    assert call["agentRuntimeArn"] == ARN
    assert call["runtimeSessionId"] == SESSION
    assert json.loads(call["payload"]) == PAYLOAD


def test_a_conflict_is_tried_again(runtime):
    runtime.answers.extend([conflict(), conflict(), {"accepted": True}])
    assert copilot_service.send(SESSION, PAYLOAD).outcome == "accepted"
    assert len(runtime.calls) == 3


def test_a_conflict_that_lasts_is_not_taken(runtime):
    runtime.answers.extend([conflict()] * 4)
    answer = copilot_service.send(SESSION, PAYLOAD)
    assert answer.outcome == "not_taken"
    assert len(runtime.calls) == 4


def test_another_error_is_not_tried_again(runtime):
    denied = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "No"}},
        "InvokeAgentRuntime",
    )
    runtime.answers.append(denied)
    assert copilot_service.send(SESSION, PAYLOAD).outcome == "not_taken"
    assert len(runtime.calls) == 1


def test_the_laptop_route_sends_no_key(monkeypatch):
    sent = []

    def post(url, json, timeout, **rest):
        sent.append(rest)
        return httpx.Response(200, json={"refused": "Busy"})

    monkeypatch.setattr(copilot_service.httpx, "post", post)
    monkeypatch.setenv("UNDERCOVER_API_KEY", "the-agents-key")
    answer = copilot_service.send(SESSION, PAYLOAD)
    assert (answer.outcome, answer.detail) == ("refused", "Busy")
    assert sent == [{}]


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (httpx.ConnectError("refused"), "not_taken"),
        (httpx.ReadTimeout("slow"), "unknown"),
    ],
)
def test_the_laptop_route_when_the_copilot_is_away_or_slow(monkeypatch, error, outcome):
    def post(*args, **kwargs):
        raise error

    monkeypatch.setattr(copilot_service.httpx, "post", post)
    assert copilot_service.send(SESSION, PAYLOAD).outcome == outcome


def test_the_laptop_route_passes_an_error_answer_on(monkeypatch):
    monkeypatch.setattr(
        copilot_service.httpx,
        "post",
        lambda *a, **k: httpx.Response(400, json={"error": "operation: wrong"}),
    )
    answer = copilot_service.send(SESSION, PAYLOAD)
    assert (answer.outcome, answer.detail) == ("not_taken", "operation: wrong")
