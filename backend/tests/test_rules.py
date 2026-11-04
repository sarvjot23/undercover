import httpx
import pytest
from fastapi.testclient import TestClient

from backend import agent_service, db, rules
from backend.api import app
from backend.tests.signing import as_handler


def decide(client, claim_id, decision="approve", payout=650.0):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "thread-test"})
    return client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "reasons": "The delay was covered. The receipts support the costs.",
            "policy_section": "3. Trip Delay",
        },
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


def test_payment_over_the_limit_waits_for_sign_off(client):
    decide(client, "CLM-1002", payout=1200.0)
    refused = client.post("/api/claims/CLM-1002/payment", json={"amount": 1200.0})
    assert refused.status_code == 409
    assert "sign-off" in refused.json()["detail"]
    assert client.get("/api/claims/CLM-1002").json()["payment"] is None

    signed = client.post("/api/claims/CLM-1002/sign-off", headers=as_handler())
    assert signed.json()["status"] == "in_progress"
    assert signed.json()["sign_off"]["handler_id"] == "HND-01"
    assert signed.json()["sign_off"]["signed_off_at"]

    paid = client.post("/api/claims/CLM-1002/payment", json={"amount": 1200.0})
    claim = client.get("/api/claims/CLM-1002").json()
    assert paid.status_code == 200
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 1200.0
    assert claim["payment"]["signed_off_by"] == "HND-01"
    assert claim["payment"]["signed_off_at"] == claim["sign_off"]["signed_off_at"]


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
    again = client.post(
        "/api/claims/CLM-1001/decision",
        json={
            "decision": "approve",
            "payout": 420.0,
            "reasons": "The same again, in other words.",
            "policy_section": "3. Trip Delay",
        },
    )
    assert again.status_code == 200
    assert again.json()["decision"]["reasons"] != "The same again, in other words."


def test_a_repeated_decision_works_after_the_claim_has_moved_on(client):
    decide(client, "CLM-1001", decision="refer", payout=0)
    again = decide(client, "CLM-1001", decision="refer", payout=0)
    assert again.status_code == 200
    assert again.json()["status"] == "decided"


def test_the_sign_off_stands_until_the_payment(client):
    decide(client, "CLM-1002", payout=1200.0)
    client.post("/api/claims/CLM-1002/sign-off", headers=as_handler())
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "in_progress"
    assert claim["sign_off"]["handler_id"] == "HND-01"
    assert claim["payment"] is None


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
    assert claim["status"] == "in_progress"
    assert claim["sign_off"]["signed_off_at"] == "2026-10-30T00:00:00+00:00"


def test_a_held_claim_is_not_being_worked(client):
    decide(client, "CLM-1002", payout=1200.0)
    client.post(
        "/api/claims/CLM-1002/steps",
        json={"kind": "tool_result", "text": "Recorded", "key": "a"},
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
    step = {"kind": "read", "text": "Section 3", "key": "same"}
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
    response = client.post(
        "/api/claims/CLM-1001/decision",
        json={
            "decision": "decline",
            "payout": 0,
            "reasons": "Not covered.",
            "policy_section": "9. General exclusions",
        },
    )
    assert response.status_code == 409


def test_steps_are_recorded_in_order(client):
    for kind, text in [("tool_call", "get_claim"), ("answer", "Approved")]:
        step = {"kind": kind, "text": text, "key": kind}
        client.post("/api/claims/CLM-1001/steps", json=step)
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [(step["kind"], step["text"]) for step in steps] == [
        ("tool_call", "get_claim"),
        ("answer", "Approved"),
    ]


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
    monkeypatch.setattr(agent_service, "tell", lambda *args: told.append(args) or True)
    started = client.post("/api/claims/CLM-1001/run", headers=as_handler()).json()
    assert started["thread_id"].startswith("CLM-1001-")
    assert told == [("/claims/CLM-1001/run", {"thread_id": started["thread_id"]})]


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


def test_a_sign_off_stands_when_the_agent_cannot_be_reached(client):
    decide(client, "CLM-1002", payout=1200.0)
    signed = client.post("/api/claims/CLM-1002/sign-off", headers=as_handler())
    assert signed.status_code == 200
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "in_progress"
    assert claim["sign_off"]["handler_id"] == "HND-01"


def test_the_link_to_the_agents_service(monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append((url, json))
        return httpx.Response(200)

    monkeypatch.setattr(agent_service.httpx, "post", post)
    monkeypatch.setenv("UNDERCOVER_AGENT", "http://127.0.0.1:8003")
    assert agent_service.tell("/dispatches", {"n": 3})
    assert calls == [("http://127.0.0.1:8003/dispatches", {"n": 3})]


def test_agent_working_until_its_answer(client):
    def working():
        return client.get("/api/claims/CLM-1001").json()["agent_working"]

    assert not working()
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "thread-test"})
    assert working()
    decide(client, "CLM-1001", decision="refer", payout=0)
    assert not working()
    step = {"kind": "tool_call", "text": "record_decision", "key": "a"}
    client.post("/api/claims/CLM-1001/steps", json=step)
    assert working()
    answer = {"kind": "answer", "text": "Done", "key": "b"}
    client.post("/api/claims/CLM-1001/steps", json=answer)
    assert not working()


def test_the_limit_comes_from_our_settings():
    assert db.load("company.json")["payout_approval_limit"] == rules.APPROVAL_LIMIT
    assert rules.APPROVAL_LIMIT == 800.0


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
    again = client.post(
        "/api/claims/CLM-1001/decision",
        json={
            "decision": "decline",
            "payout": 0,
            "reasons": "Changed my mind.",
            "policy_section": "9. General exclusions",
        },
    )
    assert again.status_code == 409
    paid = client.post("/api/claims/CLM-1001/payment", json={"amount": 420.0})
    assert paid.status_code == 200
    twice = client.post("/api/claims/CLM-1001/payment", json={"amount": 420.0})
    assert twice.status_code == 200
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["decision"]["decision"] == "approve"
    assert claim["payment"]["amount"] == 420.0


def test_the_link_says_when_the_service_is_away(monkeypatch):
    def post(url, json, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(agent_service.httpx, "post", post)
    assert agent_service.ask("/dispatches", {"n": 3}) is None
    assert not agent_service.tell("/dispatches", {"n": 3})
