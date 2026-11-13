import pytest

from backend.tests import deciding

CLAIM = "CLM-1001"
SECTION_14 = "Claims manual section 14"
EXPENSE = {
    "description": "Clinic visit",
    "amount": 500.0,
    "quantity": 1,
    "kind": "expense",
    "nights": 0,
    "hours": 0,
}


def start(client, claim_id=CLAIM):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "t"})


def calculate(client, claim_id=CLAIM):
    """Work out a payout with the payout rules, as the agent's tool does."""
    response = client.post(
        f"/api/claims/{claim_id}/payout",
        json={"benefit": "emergency_medical", "lines": [EXPENSE], "paid_by_others": 0},
    )
    assert response.status_code == 200
    return response.json()


def post(client, claim_id=CLAIM, **fields):
    """Post a decision as it is, with no calculation put on file first."""
    body = {"decision": "approve", "payout": 450.0, **deciding.FIELDS, **fields}
    return client.post(f"/api/claims/{claim_id}/decision", json=body)


def refusal(response):
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail.startswith(SECTION_14)
    return detail


@pytest.mark.parametrize(
    ("fields", "missing"),
    [
        ({"reasons": "  "}, "a reason"),
        ({"policy_section": ""}, "the section relied on"),
        ({"decided_by": " "}, "who or what made the decision"),
        ({"payout": 0}, "an approval pays more than $0"),
        ({"decision": "decline", "payout": 25.0}, "a decline or a referral pays $0"),
        ({"decision": "refer", "payout": 25.0}, "a decline or a referral pays $0"),
    ],
)
def test_the_requests_own_checks_name_section_14(client, fields, missing):
    start(client)
    assert missing in refusal(post(client, **fields))
    # They come before the claim is looked at, so any claim gets the same answer.
    assert refusal(post(client, "CLM-0000", **fields)) == refusal(
        post(client, **fields)
    )
    assert client.get(f"/api/claims/{CLAIM}").json()["decision"] is None


def test_an_approval_needs_a_calculation_on_file(client):
    start(client)
    assert "calculate_payout" in refusal(post(client))


def test_a_calculation_from_an_earlier_attempt_does_not_count(client):
    start(client)
    payout = calculate(client)["payout"]
    client.post(f"/api/claims/{CLAIM}/fail", json={"reason": "The run failed"})
    start(client)
    assert "for this attempt" in refusal(post(client, payout=payout))


def test_an_approval_must_pay_what_the_calculation_says(client):
    start(client)
    payout = calculate(client)["payout"]
    detail = refusal(post(client, payout=payout + 10))
    assert f"${payout:,.2f}" in detail


def test_the_latest_calculation_is_the_one_that_counts(client):
    start(client)
    first = calculate(client)["payout"]
    client.post(
        f"/api/claims/{CLAIM}/payout",
        json={
            "benefit": "emergency_medical",
            "lines": [{**EXPENSE, "amount": 300.0}],
            "paid_by_others": 0,
        },
    )
    assert post(client, payout=first).status_code == 422
    assert post(client, payout=first - 200).status_code == 200


def test_a_complete_approval(client):
    start(client)
    worked_out = calculate(client)
    response = post(client, payout=worked_out["payout"])
    assert response.status_code == 200
    decision = client.get(f"/api/claims/{CLAIM}").json()["decision"]
    assert decision["calculation"] == {
        "lines": worked_out["calculation"],
        "payout": worked_out["payout"],
    }
    assert decision["payout"] == worked_out["payout"]
    assert decision["decided_by"] == deciding.MAKER
    assert decision["decided_at"]
    assert decision["manual_version"] == "2026.2"
    assert decision["reasons"]
    assert decision["policy_section"]


def test_a_decline_holds_no_calculation(client):
    start(client)
    calculate(client)
    response = post(client, decision="decline", payout=0)
    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["calculation"] is None
    assert decision["decided_by"] == deciding.MAKER
    assert decision["manual_version"] == "2026.2"


def test_the_security_checks_referral_holds_its_maker(client):
    start(client)
    response = post(
        client,
        decision="refer",
        payout=0,
        policy_section="Security check: instructions found in the claim",
        decided_by="Security check",
    )
    decision = response.json()["decision"]
    assert decision["calculation"] is None
    assert decision["decided_by"] == "Security check"
