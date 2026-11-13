import logging

import pytest
from sqlalchemy import select

from backend import agent_service, db, runs
from backend.tests import deciding
from backend.tests.signing import MARCUS, as_handler

CLAIM = "CLM-1002"
NOTE = "The carrier already paid $350 for the bag. Please take it off."


def hold(client, claim_id=CLAIM, payout=1200.0):
    """An approval over the limit, waiting for sign-off."""
    deciding.decide(client, claim_id, "approve", payout, thread_id=f"{claim_id}-t")


def send_back(client, note=NOTE, claim_id=CLAIM, email=None):
    headers = as_handler() if email is None else as_handler(email)
    return client.post(
        f"/api/claims/{claim_id}/send-back", json={"note": note}, headers=headers
    )


def sign_off(client, claim_id=CLAIM):
    return client.post(f"/api/claims/{claim_id}/sign-off", headers=as_handler())


@pytest.fixture
def asked(monkeypatch):
    """The claims the app asks the agent to resume."""
    resumed = []
    monkeypatch.setattr(agent_service, "resume", resumed.append)
    return resumed


def test_a_send_back_keeps_the_decision_with_its_note(client, asked):
    hold(client)
    answer = send_back(client)
    assert answer.status_code == 200
    assert answer.json()["status"] == "sent_back"
    assert answer.json()["decision"] is None
    claim = client.get(f"/api/claims/{CLAIM}").json()
    assert claim["status"] == "sent_back"
    assert claim["decision"] is None
    assert not claim["agent_working"]
    [returned] = client.get(f"/api/claims/{CLAIM}/sent-back").json()
    assert returned["note"] == NOTE
    assert returned["handler_id"] == "HND-01"
    assert returned["handler_name"] == "Dana Whitfield"
    assert returned["sent_back_at"]
    assert returned["decision"]["payout"] == 1200.0
    assert returned["decision"]["calculation"]["payout"] == 1200.0
    assert asked == [CLAIM]


def test_a_send_back_clears_the_calculations_and_records_the_note(client, asked):
    hold(client)
    send_back(client)
    with db.engine().connect() as conn:
        left = conn.execute(
            select(db.calculations).where(db.calculations.c.claim_id == CLAIM)
        ).all()
    assert left == []
    step = client.get(f"/api/claims/{CLAIM}/steps").json()[-1]
    assert step["kind"] == "send_back"
    assert step["text"] == NOTE
    assert step["detail"] == {"by": "Dana Whitfield"}


@pytest.mark.parametrize(
    ("note", "status"),
    [("", 422), ("   ", 422), ("x" * 1001, 422), ("x" * 1000, 200)],
)
def test_the_note_is_required_and_up_to_1000_characters(client, asked, note, status):
    hold(client)
    assert send_back(client, note).status_code == status


def test_only_a_handler_who_can_sign_off_can_send_back(client, asked):
    hold(client)
    refused = send_back(client, email=MARCUS)
    assert refused.status_code == 403
    assert "can't" in refused.json()["detail"]
    assert asked == []


def test_a_claim_not_waiting_for_sign_off_is_refused(client, asked):
    deciding.decide(client, CLAIM, "approve", 300.0)
    refused = send_back(client)
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"Claim {CLAIM} is not awaiting_sign_off"


def test_an_evaluations_copy_is_refused(client, asked):
    run = client.post(
        "/api/runs",
        json={
            "kind": "evaluation",
            "n": 5,
            "set_name": "evaluation",
            "tiny": True,
            "version": None,
            "round_id": None,
        },
    ).json()
    copy_id = run["claims"][4]["claim_id"]
    hold(client, copy_id, 825.0)
    refused = send_back(client, claim_id=copy_id)
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"Claim {copy_id} is a copy for an evaluation"


def test_a_sign_off_and_a_send_back_cannot_both_go_through(client, asked):
    hold(client)
    assert sign_off(client).status_code == 200
    assert send_back(client).status_code == 409
    hold(client, "CLM-1003")
    assert send_back(client, claim_id="CLM-1003").status_code == 200
    assert sign_off(client, "CLM-1003").status_code == 409
    assert client.get("/api/claims/CLM-1003").json()["payment"] is None


def test_a_sent_back_claim_is_taken_once(client, asked):
    hold(client)
    send_back(client)
    first = client.post(f"/api/claims/{CLAIM}/take", json={"worker": "one"})
    assert first.status_code == 200
    assert client.get(f"/api/claims/{CLAIM}").json()["status"] == "in_progress"
    second = client.post(f"/api/claims/{CLAIM}/take", json={"worker": "two"})
    assert second.status_code == 409
    # The first caller holds the claim's lease.
    lease = client.post(f"/api/claims/{CLAIM}/lease", json={"worker": "two"})
    assert lease.status_code == 409


def test_only_the_agent_takes_a_claim(client, asked):
    hold(client)
    send_back(client)
    refused = client.post(
        f"/api/claims/{CLAIM}/take",
        json={"worker": "one"},
        headers={"X-API-Key": "", **as_handler()},
    )
    assert refused.status_code == 401


def test_a_dispatch_takes_sent_back_claims_with_the_waiting_ones(client, asked):
    hold(client)
    send_back(client)
    with db.engine().connect() as conn:
        assert CLAIM in runs.dispatch_claims(conn)


def test_a_claim_can_be_sent_back_more_than_once(client, asked):
    hold(client)
    send_back(client, "First look.")
    client.post(f"/api/claims/{CLAIM}/take", json={"worker": "one"})
    deciding.record(client, CLAIM, "approve", 900.0)
    send_back(client, "Second look.")
    notes = [r["note"] for r in client.get(f"/api/claims/{CLAIM}/sent-back").json()]
    assert notes == ["First look.", "Second look."]


def test_the_queue_shows_a_sent_back_claim(client, asked):
    hold(client)
    send_back(client)
    claims = {c["claim_id"]: c for c in client.get("/api/claims").json()}
    assert claims[CLAIM]["status"] == "sent_back"


def test_a_send_back_stands_when_the_agent_cannot_be_reached(client, caplog):
    hold(client)
    with caplog.at_level(logging.WARNING):
        answer = send_back(client)
    assert answer.status_code == 200
    assert f"The agent didn't take {CLAIM} to resume it" in caplog.text
    assert client.get(f"/api/claims/{CLAIM}").json()["status"] == "sent_back"
