"""The Copilot's conversations in the app: each its handler's alone, one turn at a
time, with the sign-in passed on to the Copilot and kept nowhere."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from backend import copilot_service, db
from backend.tests.signing import MARCUS, as_handler, token

STEP = {
    "kind": "claims",
    "tool": "get_claim",
    "input": "CLM-1012",
    "state": "working",
    "seconds": 0.0,
    "asked": '{"claim_id": "CLM-1012"}',
    "answer": "",
    "reason": "",
    "sources": [],
}
CARD = {
    "claim_id": "CLM-1003",
    "customer": "Maya Patel",
    "amount": 3750.0,
    "reason": "The wording covers it.",
}


@pytest.fixture
def sent(monkeypatch):
    """A stand-in Copilot on the laptop route that takes everything it's sent."""
    payloads = []

    def post(url, json, timeout, **rest):
        payloads.append({"url": url, "json": json, "rest": rest})
        return httpx.Response(200, json={"accepted": True})

    monkeypatch.setattr(copilot_service.httpx, "post", post)
    return payloads


def as_dana():
    """Dana's sign-in alone, without the agent's key the test client carries."""
    return {**as_handler(), "X-API-Key": ""}


def start(client, message="What needs me?"):
    response = client.post(
        "/api/conversations", json={"message": message}, headers=as_dana()
    )
    assert response.status_code == 202
    return response.json()


def turn_path(conversation):
    turn = conversation["turns"][-1]
    return (
        f"/api/conversations/{conversation['conversation_id']}/turns/{turn['turn_id']}"
    )


def test_a_message_starts_a_turn_and_sends_it_to_the_copilot(client, sent):
    signed = token()
    conversation = client.post(
        "/api/conversations",
        json={"message": "What needs me?"},
        headers={"Authorization": f"Bearer {signed}", "X-API-Key": ""},
    ).json()
    assert len(conversation["conversation_id"]) == 37
    assert conversation["title"] == "What needs me?"
    [turn] = conversation["turns"]
    assert turn["status"] == "working"
    [payload] = sent
    assert payload["url"] == "http://127.0.0.1:9/invocations"
    assert payload["rest"] == {}  # no key, no headers of the agent's
    assert payload["json"]["operation"] == "turn"
    assert payload["json"]["conversation_id"] == conversation["conversation_id"]
    assert payload["json"]["turn_id"] == turn["turn_id"]
    assert payload["json"]["message"] == "What needs me?"
    assert payload["json"]["token"] == signed


def test_the_sign_in_is_kept_nowhere(client, sent):
    signed = token()
    client.post(
        "/api/conversations",
        json={"message": "What needs me?"},
        headers={"Authorization": f"Bearer {signed}", "X-API-Key": ""},
    )
    with db.engine().connect() as conn:
        for table in (db.conversations, db.copilot_turns, db.copilot_steps):
            rows = conn.execute(select(table)).all()
            assert signed not in str(rows)


def test_the_copilots_steps_and_answer_are_what_the_sidebar_reads(client, sent):
    conversation = start(client)
    path = turn_path(conversation)
    client.put(f"{path}/steps/call-1", json=STEP, headers=as_dana())
    done = {**STEP, "state": "done", "seconds": 1.2, "answer": "the claim"}
    client.put(f"{path}/steps/call-1", json=done, headers=as_dana())
    finish = {"answer": "**CLM-1012** needs you.", "model_calls": 2, "cost": 0.01}
    assert client.post(f"{path}/finish", json=finish, headers=as_dana()).is_success
    found = client.get(
        f"/api/conversations/{conversation['conversation_id']}", headers=as_dana()
    ).json()
    [turn] = found["turns"]
    assert turn["status"] == "done"
    assert turn["answer"] == "**CLM-1012** needs you."
    assert (turn["model_calls"], turn["cost"]) == (2, 0.01)
    [step] = turn["steps"]
    assert (step["key"], step["state"], step["seconds"]) == ("call-1", "done", 1.2)
    assert step["answer"] == "the claim"


def test_a_paused_turn_keeps_its_card_and_an_answer_carries_it_on(client, sent):
    conversation = start(client)
    path = turn_path(conversation)
    client.post(f"{path}/pause", json={"confirmation": CARD}, headers=as_dana())
    conversation_id = conversation["conversation_id"]
    found = client.get(f"/api/conversations/{conversation_id}", headers=as_dana())
    turn = found.json()["turns"][-1]
    assert turn["status"] == "waiting"
    assert turn["confirmation"] == CARD
    answered = client.post(
        f"/api/conversations/{conversation_id}/confirmation",
        json={"confirmed": True},
        headers=as_dana(),
    )
    assert answered.json()["turns"][-1]["status"] == "working"
    assert sent[-1]["json"]["operation"] == "answer"
    assert sent[-1]["json"]["confirmed"] is True
    again = client.post(
        f"/api/conversations/{conversation_id}/confirmation",
        json={"confirmed": True},
        headers=as_dana(),
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "No confirmation is waiting"


def test_a_failed_turn_says_why_and_the_next_message_goes_ahead(client, sent):
    conversation = start(client)
    path = turn_path(conversation)
    client.post(
        f"{path}/fail", json={"reason": "The model timed out"}, headers=as_dana()
    )
    conversation_id = conversation["conversation_id"]
    found = client.get(f"/api/conversations/{conversation_id}", headers=as_dana())
    assert found.json()["turns"][-1]["error"] == "The model timed out"
    response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"message": "Try again"},
        headers=as_dana(),
    )
    assert response.status_code == 202
    assert [t["status"] for t in response.json()["turns"]] == ["failed", "working"]


def test_one_turn_at_a_time(client, sent):
    conversation = start(client)
    conversation_id = conversation["conversation_id"]

    def again():
        return client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"message": "And another thing"},
            headers=as_dana(),
        )

    working = again()
    assert working.status_code == 409
    assert (
        working.json()["detail"] == "The Copilot is still working on your last message"
    )
    client.post(
        f"{turn_path(conversation)}/pause",
        json={"confirmation": CARD},
        headers=as_dana(),
    )
    waiting = again()
    assert waiting.status_code == 409
    assert waiting.json()["detail"] == "Answer the confirmation first"


def age(turn_id, minutes):
    """Move a turn's start this many minutes into the past."""
    then = datetime.now(UTC) - timedelta(minutes=minutes)
    with db.engine().begin() as conn:
        conn.execute(
            db.copilot_turns.update()
            .where(db.copilot_turns.c.turn_id == turn_id)
            .values(started_at=then.isoformat(timespec="seconds"))
        )


def test_a_turn_working_for_over_20_minutes_is_stopped(client, sent):
    conversation = start(client)
    conversation_id = conversation["conversation_id"]
    age(conversation["turns"][0]["turn_id"], 21)
    found = client.get(f"/api/conversations/{conversation_id}", headers=as_dana())
    assert found.json()["turns"][0]["status"] == "stopped"
    response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"message": "Carry on"},
        headers=as_dana(),
    )
    assert response.status_code == 202
    turns = response.json()["turns"]
    assert [t["status"] for t in turns] == ["stopped", "working"]
    assert turns[0]["error"] == "The Copilot stopped answering"


def test_a_waiting_turn_is_never_stopped(client, sent):
    conversation = start(client)
    path = turn_path(conversation)
    client.post(f"{path}/pause", json={"confirmation": CARD}, headers=as_dana())
    age(conversation["turns"][0]["turn_id"], 60)
    found = client.get(
        f"/api/conversations/{conversation['conversation_id']}", headers=as_dana()
    )
    assert found.json()["turns"][0]["status"] == "waiting"


def test_another_handler_gets_a_404_on_someone_elses_conversation(client, sent):
    conversation = start(client)
    conversation_id = conversation["conversation_id"]
    marcus = {**as_handler(MARCUS), "X-API-Key": ""}
    base = f"/api/conversations/{conversation_id}"
    assert client.get(base, headers=marcus).status_code == 404
    message = {"message": "Hello"}
    assert (
        client.post(f"{base}/messages", json=message, headers=marcus).status_code == 404
    )
    answer = {"confirmed": True}
    assert (
        client.post(f"{base}/confirmation", json=answer, headers=marcus).status_code
        == 404
    )
    step = client.put(f"{turn_path(conversation)}/steps/x", json=STEP, headers=marcus)
    assert step.status_code == 404
    assert client.get("/api/conversations", headers=marcus).json() == []


def test_the_handlers_conversations_newest_first(client, sent):
    first = start(client, "First question")
    client.post(f"{turn_path(first)}/fail", json={"reason": "x"}, headers=as_dana())
    with db.engine().begin() as conn:
        conn.execute(
            db.conversations.update()
            .where(db.conversations.c.conversation_id == first["conversation_id"])
            .values(started_at="2026-01-01T00:00:00+00:00")
        )
    start(client, "Second question " + "and more " * 20)
    listed = client.get("/api/conversations", headers=as_dana()).json()
    assert [c["title"][:15] for c in listed] == ["Second question", "First question"]
    assert len(listed[0]["title"]) <= 80
    assert listed[0]["title"].endswith("…")


def test_the_copilots_routes_refuse_a_turn_that_has_ended(client, sent):
    conversation = start(client)
    path = turn_path(conversation)
    client.post(f"{path}/fail", json={"reason": "x"}, headers=as_dana())
    finish = {"answer": "late", "model_calls": 1, "cost": 0.0}
    response = client.post(f"{path}/finish", json=finish, headers=as_dana())
    assert response.status_code == 409


def test_a_turn_the_copilot_didnt_take_fails_with_the_reason(client):
    conversation = start(client)  # nothing listens on the Copilot's port
    [turn] = conversation["turns"]
    assert turn["status"] == "failed"
    assert turn["error"] == "The Copilot isn't running"


def test_a_message_needs_a_sign_in_and_something_to_ask(client, sent):
    assert client.post("/api/conversations", json={"message": "Hi"}).status_code == 401
    blank = client.post("/api/conversations", json={"message": "  "}, headers=as_dana())
    assert blank.status_code == 422
