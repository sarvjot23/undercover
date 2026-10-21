import pytest

from backend import main


def decide(client, claim_id, decision="approve", payout=650.0):
    client.post(f"/api/claims/{claim_id}/start")
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
    assert client.post("/api/claims/CLM-1001/start").json()["status"] == "in_progress"
    assert status(client, "CLM-1001") == "in_progress"


def test_start_twice_is_refused(client):
    client.post("/api/claims/CLM-1001/start")
    assert client.post("/api/claims/CLM-1001/start").status_code == 409


def test_start_unknown_claim(client):
    assert client.post("/api/claims/CLM-9999/start").status_code == 404


def test_approval_under_the_limit_is_decided_and_paid(client):
    assert decide(client, "CLM-1001").json()["status"] == "decided"
    paid = client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    assert paid.json() == {"claim_id": "CLM-1001", "amount": 650.0}
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["decision"]["payout"] == 650.0
    assert claim["payment"]["amount"] == 650.0
    assert claim["payment"]["signed_off_by"] is None


@pytest.mark.parametrize(
    ("payout", "expected"), [(800.0, "decided"), (800.01, "awaiting_sign_off")]
)
def test_the_limit_is_800(client, payout, expected):
    assert decide(client, "CLM-1001", payout=payout).json()["status"] == expected


def test_payment_over_the_limit_waits_for_sign_off(client):
    decide(client, "CLM-1002", payout=1200.0)
    refused = client.post("/api/claims/CLM-1002/payment", json={"amount": 1200.0})
    assert refused.status_code == 409
    assert "sign-off" in refused.json()["detail"]
    assert client.get("/api/claims/CLM-1002").json()["payment"] is None

    signed = client.post("/api/claims/CLM-1002/sign-off", json={"handler_id": "HND-01"})
    assert signed.json() == {
        "claim_id": "CLM-1002",
        "amount": 1200.0,
        "status": "decided",
    }
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 1200.0
    assert claim["payment"]["signed_off_by"] == "HND-01"


def test_sign_off_by_unknown_handler(client):
    decide(client, "CLM-1002", payout=1200.0)
    signed = client.post("/api/claims/CLM-1002/sign-off", json={"handler_id": "HND-99"})
    assert signed.status_code == 404


def test_sign_off_needs_a_claim_waiting_for_it(client):
    decide(client, "CLM-1001")
    signed = client.post("/api/claims/CLM-1001/sign-off", json={"handler_id": "HND-01"})
    assert signed.status_code == 409


def test_payment_must_match_the_payout(client):
    decide(client, "CLM-1001")
    paid = client.post("/api/claims/CLM-1001/payment", json={"amount": 700.0})
    assert paid.status_code == 409
    assert "$650.00" in paid.json()["detail"]


def test_payment_only_once(client):
    decide(client, "CLM-1001")
    client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    again = client.post("/api/claims/CLM-1001/payment", json={"amount": 650.0})
    assert again.status_code == 409


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
        client.post("/api/claims/CLM-1001/steps", json={"kind": kind, "text": text})
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [(step["kind"], step["text"]) for step in steps] == [
        ("tool_call", "get_claim"),
        ("answer", "Approved"),
    ]


def test_steps_of_unknown_claim(client):
    assert client.get("/api/claims/CLM-9999/steps").status_code == 404


def test_fail_sends_the_claim_back_to_waiting(client):
    client.post("/api/claims/CLM-1001/start")
    failed = client.post("/api/claims/CLM-1001/fail", json={"reason": "Timed out"})
    assert failed.json()["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert steps[-1]["kind"] == "error"
    assert steps[-1]["text"] == "Timed out"


def test_run_starts_the_agent(client, monkeypatch):
    runs = []
    monkeypatch.setattr(main.agent, "run", lambda *args: runs.append(args))
    started = client.post("/api/claims/CLM-1001/run").json()
    assert started["thread_id"].startswith("CLM-1001-")
    assert runs == [("CLM-1001", started["thread_id"])]


def test_run_needs_a_waiting_claim(client, monkeypatch):
    monkeypatch.setattr(main.agent, "run", lambda *args: None)
    client.post("/api/claims/CLM-1001/start")
    assert client.post("/api/claims/CLM-1001/run").status_code == 409
