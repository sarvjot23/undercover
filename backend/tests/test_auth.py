import pytest

from backend import auth
from backend.tests.signing import DANA, MARCUS, OTHER_KEY, as_handler, token

# Every action a handler takes, with a body the backend accepts.
ACTIONS = [
    ("/api/claims/CLM-1002/sign-off", None),
    ("/api/claims/CLM-1001/run", None),
    ("/api/dispatches", {"n": 3}),
    ("/api/evaluations", {"set_name": "evaluation", "tiny": True, "n": 3}),
]

BAD_TOKENS = {
    "none": None,
    "not a token": "Bearer not-a-token",
    "signed with another key": f"Bearer {token(key=OTHER_KEY)}",
    "expired": f"Bearer {token(expires_in=-60)}",
    "not a handler": f"Bearer {token('someone@example.com')}",
}


def hold_for_sign_off(client, claim_id="CLM-1002"):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "t"})
    client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": "approve",
            "payout": 1200.0,
            "reasons": "Covered by the wording. The receipts support it.",
            "policy_section": "3. Trip Delay",
        },
    )


@pytest.mark.parametrize(("path", "body"), ACTIONS)
@pytest.mark.parametrize("bad", BAD_TOKENS)
def test_every_handler_action_needs_a_valid_sign_in(client, path, body, bad):
    header = BAD_TOKENS[bad]
    headers = {"Authorization": header} if header else {}
    refused = client.post(path, json=body, headers=headers)
    assert refused.status_code == 401
    assert refused.json()["detail"] == auth.NOT_SIGNED_IN


def test_a_signed_in_handler_gets_past_the_check(client):
    # The agent's service isn't running in the tests, so the start goes no further.
    started = client.post("/api/dispatches", json={"n": 3}, headers=as_handler())
    assert started.status_code == 503


def test_a_sign_off_over_the_limit_is_refused_for_marcus(client):
    hold_for_sign_off(client)
    refused = client.post("/api/claims/CLM-1002/sign-off", headers=as_handler(MARCUS))
    assert refused.status_code == 403
    assert refused.json()["detail"] == (
        "Marcus Oyelaran can't sign off payouts over the limit"
    )
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "awaiting_sign_off"
    assert claim["sign_off"] is None


def test_a_sign_off_records_the_signed_in_handler(client):
    hold_for_sign_off(client)
    signed = client.post("/api/claims/CLM-1002/sign-off", headers=as_handler(DANA))
    assert signed.status_code == 200
    sign_off = client.get("/api/claims/CLM-1002").json()["sign_off"]
    assert sign_off["handler_id"] == "HND-01"
    assert sign_off["signed_off_at"]


def test_the_handlers_are_found_by_email(client):
    handlers = client.get("/api/handlers").json()
    assert [h["can_approve_over_limit"] for h in handlers] == [True, False, False]
    assert auth.find_handler(MARCUS) == handlers[1]
    assert auth.find_handler("nobody@example.com") is None


def test_the_keys_come_from_the_supabase_address(monkeypatch):
    monkeypatch.setenv("VITE_SUPABASE_URL", "https://project.supabase.co")
    auth.keys.cache_clear()
    assert auth.keys().uri == (
        "https://project.supabase.co/auth/v1/.well-known/jwks.json"
    )
    auth.keys.cache_clear()
