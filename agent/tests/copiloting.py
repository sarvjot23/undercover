"""The Copilot in tests: the app on SQLite as the handler signed in, a conversation
with a turn working, and the context the Copilot's graph runs with."""

from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi.testclient import TestClient

from agent import copilot_client
from agent.copilot_tools import CopilotContext
from backend import copilot_service
from backend.agent_service import Answer
from backend.api import app
from backend.tests import deciding, signing


@dataclass
class Copilot:
    """What the Copilot sent the app, and the payloads the app sent the Copilot."""

    requests: list[httpx.Request] = field(default_factory=list)
    payloads: list[dict[str, Any]] = field(default_factory=list)

    def install(self, monkeypatch: Any) -> None:
        """Point the Copilot's connection at the app, and take every payload the
        app sends the Copilot without running it."""

        def connect(token: str) -> Any:
            api = TestClient(app, headers={"Authorization": f"Bearer {token}"})
            api.event_hooks = {"request": [self.requests.append]}
            return api

        def send(conversation_id: str, payload: dict[str, Any]) -> Answer:
            self.payloads.append(payload)
            return Answer("accepted", "", {"accepted": True})

        monkeypatch.setattr(copilot_client, "connect", connect)
        monkeypatch.setattr(copilot_service, "send", send)


def as_agent() -> TestClient:
    """The app as the agent's side, to set up claims as the agent would."""
    return TestClient(app, headers=signing.as_agent())


def hold_for_sign_off(claim_id: str = "CLM-1003", payout: float = 3750.0) -> None:
    """A claim the agent approved over the limit, waiting for a sign-off."""
    with as_agent() as agent:
        deciding.decide(agent, claim_id, "approve", payout)


def begin(
    message: str, email: str = signing.DANA, memory: Any = None
) -> CopilotContext:
    """Start a conversation through the app as this handler, and the context its
    first turn runs with."""
    token = signing.token(email)
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as api:
        conversation = api.post("/api/conversations", json={"message": message}).json()
        handler = api.get("/api/me").json()
    return CopilotContext(
        token=token,
        handler=handler,
        conversation_id=conversation["conversation_id"],
        turn_id=conversation["turns"][-1]["turn_id"],
        memory=memory,
    )


def follow_up(context: CopilotContext, message: str) -> CopilotContext:
    """A next message on the same conversation, and its turn's context."""
    with TestClient(app, headers={"Authorization": f"Bearer {context.token}"}) as api:
        path = f"/api/conversations/{context.conversation_id}/messages"
        conversation = api.post(path, json={"message": message}).json()
    return CopilotContext(
        token=context.token,
        handler=context.handler,
        conversation_id=context.conversation_id,
        turn_id=conversation["turns"][-1]["turn_id"],
        memory=context.memory,
    )


def answer_card(context: CopilotContext, confirmed: bool) -> None:
    """The handler's answer to the confirmation card, through the app."""
    with TestClient(app, headers={"Authorization": f"Bearer {context.token}"}) as api:
        api.post(
            f"/api/conversations/{context.conversation_id}/confirmation",
            json={"confirmed": confirmed},
        )


def conversation(context: CopilotContext) -> dict[str, Any]:
    """The conversation as the sidebar reads it."""
    with TestClient(app, headers={"Authorization": f"Bearer {context.token}"}) as api:
        return api.get(f"/api/conversations/{context.conversation_id}").json()


def fail(context: CopilotContext, reason: str) -> None:
    """A turn failed, as the Copilot tells the app."""
    with TestClient(app, headers={"Authorization": f"Bearer {context.token}"}) as api:
        path = f"/api/conversations/{context.conversation_id}"
        api.post(f"{path}/turns/{context.turn_id}/fail", json={"reason": reason})
