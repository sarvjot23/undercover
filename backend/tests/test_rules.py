import logging

import pytest
from fastapi.testclient import TestClient

from backend import agent_service, db, rules
from backend.api import app
from backend.tests import deciding
from backend.tests.agent_answers import ACCEPTED
from backend.tests.signing import as_handler


def decide(client, claim_id, decision="approve", payout=650.0):
    return deciding.decide(
        client,
        claim_id,
        decision,
        payout,
        thread_id="thread-test",
        reasons="The delay was covered. The receipts support the costs.",
    )


def status(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()["status"]


def test_start_moves_to_in_progress(client):
    assert (
        client.post(
            "/api/claims/CLM-1001/start", json={"thread_id": "thread-test"}
        ).json()["status"]
        == "in_progress"
    )
    assert status(client, "CLM-1001") == "in_progress"


def test_start_twice_is_refused(client):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "thread-test"})
    assert (
        client.post(
            "/api/claims/CLM-1001/start", json={"thread_id": "thread-test"}
        ).status_code
        == 409
    )


def test_start_unknown_claim(client):
    assert (
        client.post(
            "/api/claims/CLM-9999/start", json={"thread_id": "thread-test"}
        ).status_code
        == 404
    )


def test_approval_under_the_limit_stays_in_progress_until_paid(client):
    assert decide(client, "CLM-1001").json()["status"] == "in_progress"
    paid = client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    assert paid.json()["status"] == "decided"
    assert paid.json()["payment"]["amount"] == 650.0
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["decision"]["payout"] == 650.0
    assert claim["payment"]["amount"] == 650.0
    assert claim["payment"]["signed_off_by"] is None


@pytest.mark.parametrize(
    ("payout", "expected"), [(800.0, "in_progress"), (800.01, "awaiting_sign_off")]
)
def test_the_limit_is_800(client, payout, expected):
    assert decide(client, "CLM-1001", payout=payout).json()["status"] == expected


def test_payment_over_the_limit_is_refused_with_the_limit(client):
    decide(client, "CLM-1002", payout=1200.0)
    refused = client.post("/api/claims/CLM-1002/payment", json={"amount": 1200.0})
    assert refused.status_code == 403
    assert "$800.00" in refused.json()["detail"]
    assert client.get("/api/claims/CLM-1002").json()["payment"] is None


def test_payment_over_the_limit_is_refused_before_the_claim_is_looked_at(client):
    for claim_id in ("CLM-1005", "CLM-9999"):
        refused = client.post(f"/api/claims/{claim_id}/payment", json={"amount": 5000})
        assert refused.status_code == 403
        assert "$800.00" in refused.json()["detail"]


def test_sign_off_needs_a_claim_waiting_for_it(client):
    decide(client, "CLM-1001")
    signed = client.post("/api/claims/CLM-1001/sign-off", headers=as_handler())
    assert signed.status_code == 409


def test_payment_must_match_the_payout(client):
    decide(client, "CLM-1001")
    paid = client.post("/api/claims/CLM-1001/payment", json={"amount": 700.0})
    assert paid.status_code == 409
    assert "$650.00" in paid.json()["detail"]


def test_a_repeated_payment_counts_as_done(client):
    decide(client, "CLM-1001")
    first = client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    again = client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    assert again.status_code == 200
    assert again.json()["payment"] == first.json()["payment"]


def test_a_stop_between_the_payment_and_its_status_is_put_right(client):
    decide(client, "CLM-1001")
    client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    with db.engine().begin() as conn:
        rules.move(conn, "CLM-1001", "decided", "in_progress")
    again = client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    assert again.status_code == 200
    assert status(client, "CLM-1001") == "decided"


def test_a_different_payment_is_refused(client):
    decide(client, "CLM-1001")
    client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    other = client.post("/api/claims/CLM-1001/payment", json={"amount": 10.0})
    assert other.status_code == 409


def test_a_repeated_decision_counts_as_done(client):
    assert decide(client, "CLM-1001", payout=420.0).status_code == 200
    again = deciding.record(
        client,
        "CLM-1001",
        "approve",
        420.0,
        reasons="The same again, in other words.",
    )
    assert again.status_code == 200
    assert again.json()["decision"]["reasons"] != "The same again, in other words."


def test_a_repeated_decision_works_after_the_claim_has_moved_on(client):
    decide(client, "CLM-1001", decision="refer", payout=0)
    again = decide(client, "CLM-1001", decision="refer", payout=0)
    assert again.status_code == 200
    assert again.json()["status"] == "decided"


def test_a_sign_off_pays_the_claim_once(client):
    decide(client, "CLM-1002", payout=1200.0)
    client.post("/api/claims/CLM-1002/sign-off", headers=as_handler())
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "decided"
    assert claim["sign_off"]["handler_id"] == "HND-01"
    assert claim["payment"]["amount"] == 1200.0
    assert claim["payment"]["signed_off_by"] == "HND-01"
    assert claim["payment"]["signed_off_at"] == claim["sign_off"]["signed_off_at"]
    again = client.post("/api/claims/CLM-1002/sign-off", headers=as_handler())
    assert again.status_code == 409
    paying = client.post("/api/claims/CLM-1002/payment", json={"amount": 1200.0})
    assert paying.status_code == 403
    with db.engine().connect() as conn:
        assert len(conn.execute(db.payments.select()).all()) == 1


def test_a_sign_off_is_saved_only_on_a_claim_waiting_for_one(client):
    decide(client, "CLM-1001", decision="refer", payout=0)
    signed = client.post("/api/claims/CLM-1001/sign-off", headers=as_handler())
    assert signed.status_code == 409
    assert client.get("/api/claims/CLM-1001").json()["sign_off"] is None


def test_a_sign_off_cut_short_is_finished_by_signing_off_again(client):
    decide(client, "CLM-1002", payout=1200.0)
    with db.engine().begin() as conn:
        conn.execute(
            db.sign_offs.insert().values(
                claim_id="CLM-1002",
                handler_id="HND-01",
                signed_off_at="2026-10-30T00:00:00+00:00",
            )
        )
    assert status(client, "CLM-1002") == "awaiting_sign_off"
    client.post("/api/claims/CLM-1002/sign-off", headers=as_handler())
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "decided"
    assert claim["sign_off"]["signed_off_at"] == "2026-10-30T00:00:00+00:00"
    assert claim["payment"]["amount"] == 1200.0


def test_a_held_claim_is_not_being_worked(client):
    decide(client, "CLM-1002", payout=1200.0)
    client.post(
        "/api/claims/CLM-1002/steps",
        json={"kind": "tool_result", "text": "Recorded", "key": "a", "detail": None},
    )
    assert not client.get("/api/claims/CLM-1002").json()["agent_working"]


def test_a_failure_cannot_undo_a_decision(client):
    decide(client, "CLM-1001")
    failed = client.post("/api/claims/CLM-1001/fail", json={"reason": "Timed out"})
    assert failed.status_code == 409
    assert status(client, "CLM-1001") == "in_progress"


def test_a_failure_forgets_the_thread(client):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "first"})
    assert client.get("/api/claims/CLM-1001").json()["thread_id"] == "first"
    client.post("/api/claims/CLM-1001/fail", json={"reason": "Timed out"})
    assert client.get("/api/claims/CLM-1001").json()["thread_id"] is None


def test_a_repeated_step_key_leaves_one_step(client):
    step = {"kind": "tool_result", "text": "Section 3", "key": "same", "detail": None}
    client.post("/api/claims/CLM-1001/steps", json=step)
    client.post("/api/claims/CLM-1001/steps", json=step)
    client.post("/api/claims/CLM-1002/steps", json=step)
    assert len(client.get("/api/claims/CLM-1001/steps").json()) == 1
    assert len(client.get("/api/claims/CLM-1002/steps").json()) == 1


def test_a_second_worker_is_refused_until_the_lease_expires(client, monkeypatch):
    lease = "/api/claims/CLM-1001/lease"
    assert client.post(lease, json={"worker": "one"}).status_code == 200
    assert client.post(lease, json={"worker": "two"}).status_code == 409
    assert client.post(lease, json={"worker": "one"}).status_code == 200
    monkeypatch.setattr(db, "now", lambda: "2099-01-01T00:00:00+00:00")
    assert client.post(lease, json={"worker": "two"}).status_code == 200


def test_a_released_lease_is_free_at_once(client):
    lease = "/api/claims/CLM-1001/lease"
    client.post(lease, json={"worker": "one"})
    client.post(f"{lease}/release", json={"worker": "two"})
    assert client.post(lease, json={"worker": "two"}).status_code == 409
    client.post(f"{lease}/release", json={"worker": "one"})
    assert client.post(lease, json={"worker": "two"}).status_code == 200


def test_the_standing_is_one_query(client):
    claim = client.get("/api/claims/CLM-1001/standing").json()
    assert claim["status"] == "waiting"
    assert set(claim) >= {"decision", "sign_off", "payment", "thread_id"}
    assert client.get("/api/claims/CLM-9999/standing").status_code == 404


def test_no_payment_on_a_decline(client):
    decide(client, "CLM-1001", decision="decline", payout=0)
    paid = client.post("/api/claims/CLM-1001/payment", json={"amount": 0})
    assert paid.status_code == 409


def test_decline_with_a_payout_is_refused(client):
    assert decide(client, "CLM-1001", decision="decline", payout=50).status_code == 422
    assert status(client, "CLM-1001") == "in_progress"


def test_referral_is_decided(client):
    assert decide(client, "CLM-1001", decision="refer", payout=0).status_code == 200
    assert status(client, "CLM-1001") == "decided"


def test_decision_needs_a_claim_in_progress(client):
    response = deciding.record(client, "CLM-1001", "decline", 0)
    assert response.status_code == 409


def test_steps_are_recorded_in_order(client):
    for kind, text in [("tool_call", "get_claim"), ("answer", "Approved")]:
        step = {"kind": kind, "text": text, "key": kind, "detail": None}
        client.post("/api/claims/CLM-1001/steps", json=step)
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [(step["kind"], step["text"]) for step in steps] == [
        ("tool_call", "get_claim"),
        ("answer", "Approved"),
    ]


LOOKUP = {
    "looked_up": "The term unattended",
    "files": [
        {
            "file": "glossary.yaml",
            "system": "The policy wording, version 2026.1",
            "owner": "Legal",
            "reviewed": "2026-09-01",
        }
    ],
}


def test_the_steps_route_returns_each_steps_detail(client):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "t"})
    for kind, detail in [("lookup", LOOKUP), ("tool_call", None)]:
        step = {"kind": kind, "text": "lookup_term", "key": kind, "detail": detail}
        assert client.post("/api/claims/CLM-1001/steps", json=step).status_code == 200
    lookup, call = client.get("/api/claims/CLM-1001/steps").json()
    assert lookup["detail"] == LOOKUP
    assert call["detail"] is None


@pytest.mark.parametrize("kind", ["lookup", "memory_search", "memory_save", "refusal"])
def test_the_agent_is_at_work_after_each_new_kind_of_step(client, kind):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "t"})
    deciding.record(client, "CLM-1001", "refer", 0)
    step = {"kind": kind, "text": "A step", "key": kind, "detail": None}
    client.post("/api/claims/CLM-1001/steps", json=step)
    assert client.get("/api/claims/CLM-1001").json()["agent_working"]


def test_steps_of_unknown_claim(client):
    assert client.get("/api/claims/CLM-9999/steps").status_code == 404


def test_fail_sends_the_claim_back_to_waiting(client):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "thread-test"})
    failed = client.post("/api/claims/CLM-1001/fail", json={"reason": "Timed out"})
    assert failed.json()["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert steps[-1]["kind"] == "error"
    assert steps[-1]["text"] == "Timed out"


def test_run_asks_the_agents_service(client, monkeypatch):
    told = []
    monkeypatch.setattr(
        agent_service, "send", lambda payload: told.append(payload) or ACCEPTED
    )
    started = client.post("/api/claims/CLM-1001/run", headers=as_handler()).json()
    assert started["thread_id"].startswith("CLM-1001-")
    assert told == [
        {
            "operation": "work_claim",
            "claim_id": "CLM-1001",
            "thread_id": started["thread_id"],
        }
    ]


def test_run_needs_the_agents_service(client):
    assert (
        client.post("/api/claims/CLM-1001/run", headers=as_handler()).status_code == 503
    )


def test_run_needs_a_waiting_claim(client):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "thread-test"})
    assert (
        client.post("/api/claims/CLM-1001/run", headers=as_handler()).status_code == 409
    )


def test_a_sign_off_reaches_the_agent_only_once_it_is_saved(client, monkeypatch):
    decide(client, "CLM-1002", payout=1200.0)
    seen = []

    def resume(claim_id):
        with db.engine().connect() as conn:
            seen.append((claim_id, rules.standing(conn, claim_id)["sign_off"]))

    monkeypatch.setattr(agent_service, "resume", resume)
    client.post("/api/claims/CLM-1002/sign-off", headers=as_handler())
    assert seen[0][0] == "CLM-1002"
    assert seen[0][1]["handler_id"] == "HND-01"


def test_a_sign_off_stands_when_the_agent_cannot_be_reached(client, caplog):
    decide(client, "CLM-1002", payout=1200.0)
    with caplog.at_level(logging.WARNING):
        signed = client.post("/api/claims/CLM-1002/sign-off", headers=as_handler())
    assert "The agent didn't take CLM-1002 to resume it" in caplog.text
    assert signed.status_code == 200
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "decided"
    assert claim["payment"]["signed_off_by"] == "HND-01"


def test_agent_working_until_its_answer(client):
    def working():
        return client.get("/api/claims/CLM-1001").json()["agent_working"]

    assert not working()
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "thread-test"})
    assert working()
    decide(client, "CLM-1001", decision="refer", payout=0)
    assert not working()
    step = {"kind": "tool_call", "text": "record_decision", "key": "a", "detail": None}
    client.post("/api/claims/CLM-1001/steps", json=step)
    assert working()
    answer = {"kind": "answer", "text": "Done", "key": "b", "detail": None}
    client.post("/api/claims/CLM-1001/steps", json=answer)
    assert not working()


def test_the_limit_starts_from_our_settings(client):
    limit = client.get("/api/settings").json()["settings"]["approval_limit"]
    assert limit == db.load("company.json")["payout_approval_limit"] == 800.0


def fail(client, claim_id="CLM-1001"):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "thread-test"})
    return client.post(f"/api/claims/{claim_id}/fail", json={"reason": "Timed out"})


def test_a_second_failure_leaves_the_claim_for_a_handler(client):
    assert fail(client).json()["status"] == "waiting"
    assert fail(client).json()["status"] == "needs_handler"
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["attempts"] == 2
    assert (
        client.post(
            "/api/claims/CLM-1001/start", json={"thread_id": "thread-test"}
        ).status_code
        == 409
    )


def test_a_backend_restart_leaves_a_claim_in_progress(client):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "thread-test"})
    with TestClient(app):
        claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "in_progress"
    assert claim["attempts"] == 0
    assert claim["thread_id"] == "thread-test"


def test_never_decided_or_paid_twice(client):
    decide(client, "CLM-1001", payout=420.0)
    again = deciding.record(client, "CLM-1001", "decline", 0)
    assert again.status_code == 409
    paid = client.post("/api/claims/CLM-1001/payment", json={"amount": 420.0})
    assert paid.status_code == 200
    twice = client.post("/api/claims/CLM-1001/payment", json={"amount": 420.0})
    assert twice.status_code == 200
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["decision"]["decision"] == "approve"
    assert claim["payment"]["amount"] == 420.0


def hold(client, claim_id="CLM-1001", **kwargs):
    return client.post(
        f"/api/claims/{claim_id}/hold",
        json={"reason": "Tool Execution Denied: over $1,000"},
        **kwargs,
    )


def test_a_payment_the_gateway_refused_waits_for_a_sign_off(client):
    decide(client, "CLM-1001")
    held = hold(client)
    assert held.json()["status"] == "awaiting_sign_off"
    assert held.json()["decision"]["payment_refused"].startswith("Tool Execution")
    signed = client.post("/api/claims/CLM-1001/sign-off", headers=as_handler())
    assert signed.json()["payment"]["amount"] == 650.0
    assert status(client, "CLM-1001") == "decided"


def test_only_an_approved_unpaid_claim_in_progress_is_held(client):
    assert hold(client).status_code == 409
    decide(client, "CLM-1002", decision="decline", payout=0)
    assert hold(client, "CLM-1002").status_code == 409
    decide(client, "CLM-1003", payout=1200.0)
    assert hold(client, "CLM-1003").status_code == 409
    decide(client, "CLM-1004")
    client.post("/api/claims/CLM-1004/payment", json={"amount": 650.0})
    assert hold(client, "CLM-1004").status_code == 409


def test_only_the_agent_holds_a_payment(client):
    decide(client, "CLM-1001")
    assert hold(client, headers={"X-API-Key": ""}).status_code == 401
