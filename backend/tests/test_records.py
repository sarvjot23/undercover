from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from backend import db
from backend.api import app


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
        "attempts": 0,
        "thread_id": None,
        "signed_off": False,
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


def test_version_1_is_the_claim_agent_as_it_was(client):
    current = client.get("/api/configuration/current").json()
    assert current["version"] == 1
    assert current["instructions"].startswith("You are the UnderCover Agent.")
    assert (current["model"], current["reasoning"]) == ("openai/gpt-6-luna", "low")
    assert set(current) == {"version", "instructions", "model", "reasoning"}
    assert "data/evals" not in current["instructions"]


def test_handlers(client):
    names = [handler["name"] for handler in client.get("/api/handlers").json()]
    assert names == ["Dana Whitfield", "Marcus Oyelaran", "Priya Raman"]


def test_seed_runs_once(client):
    db.init()
    assert len(client.get("/api/claims").json()) == 25


def test_seed_reads_only_the_answer_key_from_the_evals(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "seed.db"))
    read = []
    original = Path.read_text

    def spy(self, *args, **kwargs):
        read.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    db.init()
    evals = {path.name for path in read if "evals" in path.parts}
    assert evals == {
        "decisions.json",
        "held_out_claims.json",
        "held_out_decisions.json",
    }


def test_the_answer_key_stays_out_of_the_queue(client):
    claims = client.get("/api/claims").json()
    assert [claim["claim_id"] for claim in claims][-1] == "CLM-1025"
    assert client.get("/api/claims/CLM-1101").status_code == 404
    with db.engine().connect() as conn:
        held_out = conn.execute(select(func.count()).select_from(db.held_out_claims))
        assert held_out.scalar() == 25
        key = conn.execute(select(func.count()).select_from(db.handler_decisions))
        assert key.scalar() == 50


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


def test_reseed_starts_again_from_the_data(client):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "thread-test"})
    client.post(
        "/api/claims/CLM-1001/decision",
        json={
            "decision": "refer",
            "payout": 0,
            "reasons": "Needs a handler.",
            "policy_section": "11. How to claim",
        },
    )
    db.reseed()
    claims = client.get("/api/claims").json()
    assert {claim["status"] for claim in claims} == {"waiting"}
    assert client.get("/api/claims/CLM-1001/steps").json() == []
    assert client.get("/api/claims/CLM-1001").json()["decision"] is None


def test_a_real_database_comes_only_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "local.db"))
    assert db.engine().dialect.name == "sqlite"
    monkeypatch.setenv("DATABASE_URL", "")
    assert db.engine().dialect.name == "sqlite"


def test_postgres_keeps_to_its_schema_and_four_connections():
    engine = db.postgres_engine("postgresql://user:secret@example.invalid:5432/app")
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    assert engine.pool.size() + engine.pool._max_overflow == 4  # type: ignore[attr-defined]


def test_every_table_compiles_for_postgres():
    for table in db.metadata.sorted_tables:
        created = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {table.name}" in created
        assert "undercover." not in created


def test_reseed_leaves_the_checkpointers_tables_in_place_but_empty(client):
    with db.engine().begin() as conn:
        conn.execute(text("CREATE TABLE checkpoints (thread_id TEXT)"))
        conn.execute(text("INSERT INTO checkpoints VALUES ('CLM-1001-a')"))
    db.reseed()
    with db.engine().connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM checkpoints")).scalar()
    assert count == 0


def test_warming_up_is_for_supabase_only(monkeypatch):
    monkeypatch.setattr(db, "engine", lambda: pytest.fail("Should not connect"))
    db.warm_up()


def test_warming_up_opens_every_connection(monkeypatch):
    opened = []

    class Engine:
        def connect(self):
            opened.append(1)
            return SimpleNamespace(execute=lambda query: None, close=lambda: None)

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/app")
    monkeypatch.setattr(db, "engine", Engine)
    db.warm_up()
    assert len(opened) == db.MAX_CONNECTIONS
