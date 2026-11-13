import functools

import httpx
import pytest

from agent import client, improver_client

KEY = "agent-key-0123456789abcdefghijklmnopqrstuv"


@pytest.fixture
def sent(monkeypatch) -> list[str | None]:
    """The key on each request the agent sends, to a backend that answers {}."""
    keys: list[str | None] = []

    def answer(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers.get("X-API-Key"))
        return httpx.Response(200, json={"status": "working"})

    transport = httpx.MockTransport(answer)
    monkeypatch.setattr(
        client.httpx, "Client", functools.partial(httpx.Client, transport=transport)
    )
    return keys


def test_every_request_to_the_backend_carries_the_key(monkeypatch, sent):
    monkeypatch.setenv("UNDERCOVER_API_KEY", KEY)
    with client.backend() as backend:
        backend.get("/api/claims")
    improver_client.find(1)
    assert sent == [KEY, KEY]


def test_the_key_is_read_when_each_request_is_made(monkeypatch, sent):
    monkeypatch.delenv("UNDERCOVER_API_KEY", raising=False)
    with client.backend() as backend:
        backend.get("/api/claims")
    monkeypatch.setenv("UNDERCOVER_API_KEY", KEY)
    with client.backend() as backend:
        backend.get("/api/claims")
    assert sent == ["", KEY]


def test_the_agent_reaches_the_app_at_undercover_api(monkeypatch, sent):
    monkeypatch.setenv("UNDERCOVER_API", "https://app.example")
    with client.backend() as backend:
        assert str(backend.base_url) == "https://app.example"
    monkeypatch.delenv("UNDERCOVER_API")
    with client.backend() as backend:
        assert str(backend.base_url) == "http://127.0.0.1:8000"
