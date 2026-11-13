import json

import httpx
import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    IncompleteReadError,
    ReadTimeoutError,
)

from backend import agent_service

PAYLOAD = {"operation": "start_dispatch", "n": 3}
ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/undercover_agent-x"


@pytest.fixture
def laptop(monkeypatch):
    """The laptop route, with a stand-in for the agent behind httpx.post."""
    sent = []
    answers = []

    def post(url, json, headers, timeout):
        sent.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(agent_service.httpx, "post", post)
    monkeypatch.setenv("UNDERCOVER_AGENT", "http://127.0.0.1:8080")
    monkeypatch.setenv("UNDERCOVER_API_KEY", "the-agents-key")
    return sent, answers


def test_the_laptop_route_posts_the_payload_with_the_key(laptop):
    sent, answers = laptop
    answers.append(httpx.Response(200, json={"accepted": True}))
    answer = agent_service.send(PAYLOAD)
    assert answer.outcome == "accepted"
    assert sent == [
        {
            "url": "http://127.0.0.1:8080/invocations",
            "json": PAYLOAD,
            "headers": {"Authorization": "Bearer the-agents-key"},
            "timeout": 10,
        }
    ]


def test_the_laptop_route_defaults_to_port_8080(laptop, monkeypatch):
    sent, answers = laptop
    monkeypatch.delenv("UNDERCOVER_AGENT")
    answers.append(httpx.Response(200, json={"accepted": True}))
    agent_service.send(PAYLOAD)
    assert sent[0]["url"] == "http://127.0.0.1:8080/invocations"


def test_the_laptop_route_passes_a_refusal_on(laptop):
    _, answers = laptop
    answers.append(httpx.Response(200, json={"refused": "Dispatch 7 is running"}))
    assert agent_service.send(PAYLOAD)[:2] == ("refused", "Dispatch 7 is running")


def test_on_the_laptop_a_failed_connection_was_not_taken(laptop):
    _, answers = laptop
    answers.append(httpx.ConnectError("refused"))
    assert agent_service.send(PAYLOAD)[:2] == ("not_taken", agent_service.AWAY)


def test_on_the_laptop_an_error_answer_was_not_taken(laptop):
    _, answers = laptop
    answers.append(httpx.Response(401, json={"error": "The agent's key is wrong"}))
    answer = agent_service.send(PAYLOAD)
    assert answer[:2] == ("not_taken", "The agent's key is wrong")


@pytest.mark.parametrize(
    "trouble",
    [
        httpx.ReadTimeout("slow"),
        httpx.RemoteProtocolError("cut off"),
        httpx.Response(200, content=b'{"accep'),
    ],
)
def test_on_the_laptop_a_timeout_or_cut_off_answer_is_unknown(laptop, trouble):
    _, answers = laptop
    answers.append(trouble)
    assert agent_service.send(PAYLOAD).outcome == "unknown"


class Runtime:
    """A stand-in for boto3's bedrock-agentcore client."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.made = []

    def client(self, service, config):
        self.made.append((service, config))
        return self

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"response": self.answer}


class Stream:
    """The answer's stream, which may break while it's read."""

    def __init__(self, body=b"", broken=None):
        self.body = body
        self.broken = broken

    def read(self):
        if self.broken:
            raise self.broken
        return self.body


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("UNDERCOVER_AGENT_RUNTIME", ARN)

    def use(answer):
        stand_in = Runtime(answer)
        monkeypatch.setattr(agent_service.boto3, "client", stand_in.client)
        return stand_in

    return use


def test_the_runtime_route_sends_the_payload_in_a_new_session(runtime):
    stand_in = runtime(Stream(json.dumps({"accepted": True}).encode()))
    assert agent_service.send(PAYLOAD).outcome == "accepted"
    agent_service.send(PAYLOAD)
    first, second = stand_in.calls
    assert first["agentRuntimeArn"] == ARN
    assert json.loads(first["payload"]) == PAYLOAD
    assert len(first["runtimeSessionId"]) >= 33
    assert first["runtimeSessionId"] != second["runtimeSessionId"]
    service, config = stand_in.made[0]
    assert service == "bedrock-agentcore"
    assert config.retries == {"total_max_attempts": 1}
    assert (config.connect_timeout, config.read_timeout) == (5, 20)


def test_the_runtime_route_passes_a_refusal_on(runtime):
    runtime(Stream(json.dumps({"refused": "Dispatch 7 is running"}).encode()))
    assert agent_service.send(PAYLOAD)[:2] == ("refused", "Dispatch 7 is running")


def test_on_runtime_a_failed_connection_was_not_taken(runtime):
    runtime(EndpointConnectionError(endpoint_url="https://bedrock-agentcore"))
    assert agent_service.send(PAYLOAD).outcome == "not_taken"


def test_on_runtime_an_error_answer_was_not_taken(runtime):
    error = {"Error": {"Code": "AccessDeniedException", "Message": "Not allowed"}}
    runtime(ClientError(error, "InvokeAgentRuntime"))
    answer = agent_service.send(PAYLOAD)
    assert answer.outcome == "not_taken"
    assert "Not allowed" in answer.detail


def test_on_runtime_a_read_timeout_is_unknown(runtime):
    runtime(ReadTimeoutError(endpoint_url="https://bedrock-agentcore"))
    assert agent_service.send(PAYLOAD).outcome == "unknown"


@pytest.mark.parametrize(
    "stream",
    [
        Stream(broken=IncompleteReadError(actual_bytes=3, expected_bytes=20)),
        Stream(b'{"accep'),
    ],
)
def test_on_runtime_an_answer_cut_off_is_unknown(runtime, stream):
    runtime(stream)
    assert agent_service.send(PAYLOAD).outcome == "unknown"


def test_a_resume_the_agent_did_not_take_is_logged(laptop, caplog):
    _, answers = laptop
    answers.append(httpx.ConnectError("refused"))
    agent_service.resume("CLM-1001")
    assert "The agent didn't take CLM-1001 to resume it" in caplog.text
