from pathlib import Path

from backend import db
from backend.main import app


def test_queue_is_seeded_waiting(client):
    claims = client.get("/api/claims").json()
    assert len(claims) == 25
    assert {claim["status"] for claim in claims} == {"waiting"}
    assert claims[0] == {
        "claim_id": "CLM-1001",
        "customer_name": "Maya Patel",
        "claim_type": "trip_delay",
        "summary": "Flight home canceled by the airline, rebooked the next morning",
        "amount_claimed": 420.0,
        "submitted_on": "2026-06-24",
        "status": "waiting",
        "agent_working": False,
        "decision": None,
        "payout": None,
    }


def test_claim_in_full(client):
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["policy"]["policy_id"] == "POL-2001"
    assert claim["plan"]["plan"] == "premium"
    assert claim["plan"]["trip_delay_max"] == 800.0
    assert claim["customer"]["name"] == "Maya Patel"
    assert claim["customer"]["previous_claims"][0]["claim_id"] == "CLM-0412"
    assert claim["decision"] is None
    assert claim["payment"] is None


def test_claim_leaves_out_personal_details(client):
    customer = client.get("/api/claims/CLM-1001").json()["customer"]
    assert set(customer) == {"customer_id", "name", "customer_since", "previous_claims"}


def test_unknown_claim(client):
    assert client.get("/api/claims/CLM-9999").status_code == 404


def test_policy_wording(client):
    text = client.get("/api/policy-wording").json()["text"]
    assert text.startswith("# UnderCover Travel Insurance: Policy Wording")


def test_instructions(client):
    text = client.get("/api/instructions").json()["text"]
    assert text.startswith("You are the UnderCover Agent.")


def test_handlers(client):
    names = [handler["name"] for handler in client.get("/api/handlers").json()]
    assert names == ["Dana Whitfield", "Marcus Oyelaran", "Priya Raman"]


def test_seed_runs_once(client):
    db.init()
    assert len(client.get("/api/claims").json()) == 25


def test_seed_never_reads_the_evals(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "seed.db"))
    read = []
    original = Path.read_text

    def spy(self, *args, **kwargs):
        read.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    db.init()
    assert read
    assert all("evals" not in path.parts for path in read)


def test_no_response_holds_eval_fields(client):
    responses = [client.get("/api/claims").text]
    for claim in client.get("/api/claims").json():
        responses.append(client.get(f"/api/claims/{claim['claim_id']}").text)
    text = "".join(responses)
    for field in ("difficulty", "failure_class", "over_approval_limit", "tiny"):
        assert f'"{field}"' not in text


def test_every_operation_is_documented_with_no_optional_inputs():
    schema = app.openapi()
    for path in schema["paths"].values():
        for operation in path.values():
            assert operation["operationId"]
            assert "\n" not in operation["description"]
            assert all(param["required"] for param in operation.get("parameters", []))
            if "requestBody" in operation:
                assert operation["requestBody"]["required"]
    for model in schema["components"]["schemas"].values():
        if model["title"] in {"HTTPValidationError", "ValidationError"}:
            continue
        assert set(model["properties"]) == set(model.get("required", []))
