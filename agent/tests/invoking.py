"""Calling the agent's AgentCore app in the tests, as the app does."""

from typing import Any

from starlette.testclient import TestClient

from agent import entrypoint
from backend import agent_service
from backend.tests.signing import AGENT_KEY


def invoke(payload: dict[str, Any], key: str | None = AGENT_KEY) -> Any:
    """Post a payload to the agent's /invocations, with the agent's key or none."""
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    with TestClient(entrypoint.app) as agent:
        return agent.post("/invocations", json=payload, headers=headers)


def ping() -> str:
    """The agent's /ping status."""
    with TestClient(entrypoint.app) as agent:
        return agent.get("/ping").json()["status"]


def connect(monkeypatch: Any) -> None:
    """Connect the app's laptop route to the agent in this process, as npm run dev
    connects them on the laptop."""
    monkeypatch.setattr(
        agent_service,
        "on_laptop",
        lambda payload: agent_service.read(invoke(payload).json()),
    )
