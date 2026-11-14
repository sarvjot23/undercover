"""The reads the Copilot needs: who is signed in, customers, payouts over the limit
and an evaluation's measures without the handlers' answers."""

from backend.tests import deciding
from backend.tests.signing import MARCUS, as_handler


def test_who_am_i_answers_the_handler_signed_in(client):
    me = client.get("/api/me", headers=as_handler(MARCUS)).json()
    assert me["handler_id"] == "HND-02"
    assert me["name"] == "Marcus Oyelaran"
    assert me["can_approve_over_limit"] is False


def test_who_am_i_refuses_the_agents_key_alone(client):
    assert client.get("/api/me").status_code == 401


def test_a_customer_with_policies_earlier_claims_and_claims_in_the_queue(client):
    customer = client.get("/api/customers/CUS-3001", headers=as_handler()).json()
    assert customer["name"] == "Maya Patel"
    assert [p["policy_id"] for p in customer["policies"]] == ["POL-2001"]
    assert customer["previous_claims"][0]["claim_id"] == "CLM-0412"
    queue = customer["claims_in_queue"]
    assert queue[0]["claim_id"] == "CLM-1001"
    assert queue[0]["status"] == "waiting"
    assert queue[0]["decision"] is None


def test_a_customer_that_isnt_there_is_a_404(client):
    response = client.get("/api/customers/CUS-0000", headers=as_handler())
    assert response.status_code == 404


def test_customers_are_found_by_part_of_a_name_in_any_case(client):
    found = client.get("/api/customers/named/maya PAT", headers=as_handler()).json()
    assert found == [
        {
            "customer_id": "CUS-3001",
            "name": "Maya Patel",
            "customer_since": "2023-04-11",
        }
    ]
    nobody = client.get("/api/customers/named/Zebedee", headers=as_handler())
    assert nobody.json() == []


def test_the_customer_reads_need_a_handler(client):
    assert client.get("/api/customers/CUS-3001").status_code == 401
    assert client.get("/api/customers/named/Maya").status_code == 401


def over_limit(client):
    return client.get("/api/payouts/over-limit", headers=as_handler()).json()


def test_none_paid_over_the_limit_on_a_fresh_seed(client):
    assert over_limit(client) == {
        "approval_limit": 800.0,
        "paid_over_limit": 0,
        "signed_off": 0,
        "claim_ids": [],
    }


def test_a_payout_over_the_limit_counts_with_its_sign_off(client):
    deciding.decide(client, "CLM-1003", "approve", 3750.0)
    client.post("/api/claims/CLM-1003/sign-off", headers=as_handler())
    deciding.decide(client, "CLM-1001", "approve", 420.0)
    client.post("/api/claims/CLM-1001/payment", json={"amount": 420.0})
    assert over_limit(client) == {
        "approval_limit": 800.0,
        "paid_over_limit": 1,
        "signed_off": 1,
        "claim_ids": ["CLM-1003"],
    }


def test_an_evaluations_copy_is_never_counted(client):
    started = client.post(
        "/api/runs",
        json={
            "kind": "evaluation",
            "n": 1,
            "set_name": "evaluation",
            "tiny": True,
            "version": None,
            "round_id": None,
        },
    ).json()
    copy = started["claims"][0]["claim_id"]
    deciding.decide(client, copy, "approve", 900.0)
    client.post(f"/api/claims/{copy}/payment", json={"amount": 900.0})
    assert over_limit(client)["paid_over_limit"] == 0


def test_an_evaluations_measures_leave_out_its_claims(client):
    started = client.post(
        "/api/runs",
        json={
            "kind": "evaluation",
            "n": 1,
            "set_name": "evaluation",
            "tiny": True,
            "version": None,
            "round_id": None,
        },
    ).json()
    run_id = started["run_id"]
    measures = client.get(
        f"/api/evaluations/{run_id}/measures", headers=as_handler()
    ).json()
    assert measures["run_id"] == run_id
    assert measures["status"] == "running"
    assert "claims" not in measures
    assert "handler_decision" not in str(measures)


def test_a_dispatch_has_no_measures(client):
    started = client.post(
        "/api/runs",
        json={
            "kind": "dispatch",
            "n": 1,
            "set_name": None,
            "tiny": False,
            "version": None,
            "round_id": None,
        },
    ).json()
    response = client.get(
        f"/api/evaluations/{started['run_id']}/measures", headers=as_handler()
    )
    assert response.status_code == 404
