from backend.tests.signing import MARCUS, as_handler

START = {
    "approval_limit": 800.0,
    "objectives": {"accuracy": 0.6, "grade": 1.0},
    "noise": {
        "accuracy": 0.1,
        "grade": 0.15,
        "cost_per_claim": 0.15,
        "seconds_per_claim": 0.15,
    },
    "tolerance": {
        "accuracy": 0.1,
        "grade": 0.15,
        "cost_per_claim": 1.0,
        "seconds_per_claim": 0.25,
    },
    "round_spending_limit": 0.5,
    "agents_at_once": 25,
}


def change(client, email=None, **values):
    headers = as_handler(email) if email else as_handler()
    return client.put("/api/settings", json={**START, **values}, headers=headers)


def decide(client, claim_id, payout):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "t"})
    return client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": "approve",
            "payout": payout,
            "reasons": "Covered by the wording. The receipts support it.",
            "policy_section": "3. Trip Delay",
        },
    ).json()


def test_the_settings_start_with_the_labs_values_and_our_limit(client):
    found = client.get("/api/settings").json()
    assert found["settings"] == START
    assert found["changes"] == []
    assert len(found["models"]) == 3


def test_a_new_limit_applies_to_the_next_decision_and_a_held_payout_stays_held(
    client,
):
    held = decide(client, "CLM-1002", 900.0)
    assert held["status"] == "awaiting_sign_off"
    assert held["decision"]["approval_limit"] == 800.0

    changed = change(client, approval_limit=1000.0)
    assert changed.status_code == 200
    [recorded] = changed.json()["changes"]
    assert recorded["name"] == "approval_limit"
    assert (recorded["before"], recorded["after"]) == (800.0, 1000.0)
    assert recorded["handler_id"] == "HND-01"
    assert recorded["changed_at"]

    after = decide(client, "CLM-1003", 900.0)
    assert after["status"] == "in_progress"
    assert after["decision"]["approval_limit"] == 1000.0
    assert client.get("/api/claims/CLM-1002").json()["status"] == "awaiting_sign_off"
    refused = client.post("/api/claims/CLM-1002/payment", json={"amount": 900.0})
    assert refused.status_code == 409
    assert "$800.00" in refused.json()["detail"]
    paid = client.post("/api/claims/CLM-1003/payment", json={"amount": 900.0})
    assert paid.status_code == 200


def test_the_payout_rules_use_the_limit_in_the_settings(client):
    change(client, approval_limit=100.0)
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "t"})
    worked_out = client.post(
        "/api/claims/CLM-1001/payout",
        json={
            "benefit": "trip_delay",
            "lines": [
                {
                    "description": "Taxi",
                    "amount": 150.0,
                    "quantity": 1,
                    "kind": "expense",
                    "nights": 0,
                    "hours": 0,
                }
            ],
            "paid_by_others": 0,
        },
    ).json()
    assert worked_out["needs_sign_off"] is True


def test_only_what_changed_is_recorded(client):
    change(client)
    change(client, noise={**START["noise"], "accuracy": 0.05}, agents_at_once=10)
    found = client.get("/api/settings").json()
    assert [entry["name"] for entry in found["changes"]] == [
        "agents_at_once",
        "noise.accuracy",
    ]
    assert found["settings"]["agents_at_once"] == 10


def test_a_settings_change_is_refused_for_marcus(client):
    refused = change(client, MARCUS, approval_limit=5000.0)
    assert refused.status_code == 403
    assert refused.json()["detail"] == (
        "Marcus Oyelaran can't sign off payouts over the limit, "
        "so can't change the settings"
    )
    assert client.get("/api/settings").json()["changes"] == []


def test_a_settings_change_is_refused_for_anyone_signed_out(client):
    refused = client.put("/api/settings", json=START)
    assert refused.status_code == 401


def test_a_setting_out_of_range_is_refused(client):
    assert change(client, agents_at_once=26).status_code == 422
    assert change(client, approval_limit=0).status_code == 422
