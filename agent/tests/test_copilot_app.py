"""The Copilot's AgentCore app: its operations, the sign-in checked first, a turn as
an async task, and a turn carried from the app through the Copilot and back."""

import os
import threading
import time
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from starlette.testclient import TestClient

from agent import copilot_app, copilot_client, copilot_graph, model, ready
from agent.tests import copiloting
from agent.tests.stubs import call, script
from backend import agent_service, copilot_service
from backend.agent_service import Answer
from backend.api import app as backend_app
from backend.tests import signing

REAL_SPAWN = copilot_app.spawn
CLAIM = "CLM-1003"


def invoke(payload: dict[str, Any]) -> Any:
    """Post a payload to the Copilot's /invocations, with no key."""
    with TestClient(copilot_app.app) as copilot:
        return copilot.post("/invocations", json=payload)


def ping() -> str:
    with TestClient(copilot_app.app) as copilot:
        return copilot.get("/ping").json()["status"]


def wait_for(done):
    for _ in range(100):
        if done():
            return
        time.sleep(0.05)
    raise AssertionError("never happened")


@pytest.fixture
def connected(requests, monkeypatch):
    """The app and the Copilot in this process, connected as npm run dev connects
    them, with the claim agent taking any work it's given."""

    def connect(token: str) -> Any:
        return TestClient(backend_app, headers={"Authorization": f"Bearer {token}"})

    monkeypatch.setattr(copilot_client, "connect", connect)
    monkeypatch.setattr(
        copilot_service,
        "on_laptop",
        lambda payload: agent_service.read(invoke(payload).json()),
    )
    monkeypatch.setattr(
        agent_service, "send", lambda payload: Answer("accepted", "", {})
    )


def as_dana() -> TestClient:
    return TestClient(backend_app, headers=signing.as_handler())


def say(message: str, conversation_id: str | None = None) -> dict[str, Any]:
    """Dana's message, through the app, as the sidebar sends it."""
    path = (
        f"/api/conversations/{conversation_id}/messages"
        if conversation_id
        else "/api/conversations"
    )
    with as_dana() as app:
        return app.post(path, json={"message": message}).json()


def turn_payload(token: str) -> dict[str, Any]:
    return {
        "operation": "turn",
        "conversation_id": "conv-0123456789abcdef0123456789abcdef",
        "turn_id": 1,
        "message": "What needs me?",
        "token": token,
    }


def test_the_health_check_answers_without_a_key():
    assert invoke({"operation": "health"}).json() == {"healthy": True}


def test_a_wrong_payload_gets_a_400_that_never_shows_the_sign_in():
    payload = {**turn_payload("secret-sign-in"), "turn_id": "not a number"}
    answer = invoke(payload)
    assert answer.status_code == 400
    assert "turn_id" in answer.json()["error"]
    assert "secret-sign-in" not in answer.text


def test_a_sign_in_the_app_doesnt_accept_ends_before_any_model_call(
    connected, monkeypatch
):
    worked = []
    monkeypatch.setattr(copilot_graph, "turn", lambda *args: worked.append(args))
    answer = invoke(turn_payload("not-a-sign-in")).json()
    assert answer == {
        "refused": "The app didn't accept the sign-in: Sign in as a handler first"
    }
    assert worked == []


def test_a_turn_through_the_app_ends_with_the_answer(connected, monkeypatch):
    monkeypatch.setattr(
        model,
        "copilot_model",
        lambda: script(call("list_claims"), AIMessage("Nothing needs you yet.")),
    )
    conversation = say("What needs me?")
    with as_dana() as app:
        found = app.get(f"/api/conversations/{conversation['conversation_id']}").json()
    [turn] = found["turns"]
    assert turn["status"] == "done"
    assert turn["answer"] == "Nothing needs you yet."
    assert [s["tool"] for s in turn["steps"]] == ["list_claims"]


def test_a_failed_turn_tells_the_app_why_and_the_next_message_works(
    connected, monkeypatch
):
    real_turn = copilot_graph.turn
    failures = [RuntimeError("The model is down")]

    def fails_once(context, message):
        if failures:
            raise failures.pop()
        real_turn(context, message)

    monkeypatch.setattr(copilot_graph, "turn", fails_once)
    monkeypatch.setattr(model, "copilot_model", lambda: script(AIMessage("Back.")))
    conversation = say("What needs me?")
    conversation_id = conversation["conversation_id"]
    with as_dana() as app:
        found = app.get(f"/api/conversations/{conversation_id}").json()
    assert found["turns"][0]["status"] == "failed"
    assert found["turns"][0]["error"] == "The model is down"
    again = say("Try again", conversation_id)
    assert [t["status"] for t in again["turns"]] == ["failed", "done"]
    assert again["turns"][1]["answer"] == "Back."


def test_a_pause_through_the_app_is_answered_on_a_fresh_graph(connected, monkeypatch):
    copiloting.hold_for_sign_off()
    replies = iter(
        [
            script(call("sign_off_claim", claim_id=CLAIM)),
            script(AIMessage("Signed off and paid $3,750.00.")),
        ]
    )
    monkeypatch.setattr(model, "copilot_model", lambda: next(replies))
    conversation = say("Sign off CLM-1003")
    conversation_id = conversation["conversation_id"]
    with as_dana() as app:
        waiting = app.get(f"/api/conversations/{conversation_id}").json()
        assert waiting["turns"][0]["status"] == "waiting"
        assert waiting["turns"][0]["confirmation"]["amount"] == 3750.0
        app.post(
            f"/api/conversations/{conversation_id}/confirmation",
            json={"confirmed": True},
        )
        done = app.get(f"/api/conversations/{conversation_id}").json()
        claim = app.get(f"/api/claims/{CLAIM}").json()
    assert done["turns"][0]["status"] == "done"
    assert done["turns"][0]["answer"] == "Signed off and paid $3,750.00."
    assert claim["payment"]["signed_off_by"] == "HND-01"


def test_the_ping_is_busy_while_a_turn_works_and_healthy_after(connected, monkeypatch):
    monkeypatch.setattr(copilot_app, "spawn", REAL_SPAWN)
    release = threading.Event()
    monkeypatch.setattr(
        copilot_graph, "turn", lambda context, message: release.wait(10)
    )
    token = signing.token()
    assert ping() == "Healthy"
    assert invoke(turn_payload(token)).json() == {"accepted": True}
    assert ping() == "HealthyBusy"
    release.set()
    wait_for(lambda: ping() == "Healthy")


@pytest.fixture
def on_runtime(monkeypatch):
    """On Runtime: the deployment names all three credentials, and a stand-in for
    Identity gives each its value, counting the fetches."""
    fetched = []

    def requires_api_key(*, provider_name):
        def decorator(func):
            def wrapper():
                fetched.append(provider_name)
                return func(api_key=f"value-from-{provider_name}")

            return wrapper

        return decorator

    monkeypatch.setattr(ready, "requires_api_key", requires_api_key)
    for name in ("UNDERCOVER_API_KEY", "OPENROUTER_API_KEY", "DATABASE_URL"):
        monkeypatch.setenv(f"AGENTCORE_CREDENTIAL_{name}_NAME", f"{name}-provider")
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(ready.state, "copilot", False)
    monkeypatch.setattr(ready, "open_pool", lambda: None)
    return fetched


def test_on_runtime_the_copilot_fetches_only_its_two_credentials(on_runtime):
    assert invoke({"operation": "health"}).json() == {"healthy": True}
    assert sorted(on_runtime) == [
        "DATABASE_URL-provider",
        "OPENROUTER_API_KEY-provider",
    ]
    assert "UNDERCOVER_API_KEY" not in os.environ
    invoke({"operation": "health"})
    assert len(on_runtime) == 2  # once in its process
