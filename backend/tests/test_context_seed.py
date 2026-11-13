import json
from pathlib import Path

from sqlalchemy import select

from backend import db
from backend.tests.signing import as_handler


def test_seeding_reads_the_plans_and_documents_from_context(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "seed.db"))
    read = []
    original = Path.read_text

    def spy(self, *args, **kwargs):
        read.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    db.init()
    names = {(path.parent.name, path.name) for path in read}
    assert {
        ("context", "plans.yaml"),
        ("context", "policy_wording.md"),
        ("context", "claims_manual.md"),
    } <= names
    for name in ("plans.json", "policy_wording.md", "claims_manual.md"):
        assert ("data", name) not in names


def test_the_plans_have_the_same_limits_as_before(client):
    before = db.load("plans.json")
    with db.engine().connect() as conn:
        seeded = {
            plan: json.loads(body)
            for plan, body in conn.execute(select(db.plans.c.plan, db.plans.c.body))
        }
    for plan in before["plans"]:
        assert seeded[plan["plan"]].items() >= plan.items()
        assert seeded[plan["plan"]]["deductible_applies_to"] == [
            "baggage",
            "emergency_medical",
        ]
        assert seeded[plan["plan"]]["add_ons"] == before["add_ons"]


def test_the_documents_are_seeded_with_their_versions_and_sources(client):
    with db.engine().connect() as conn:
        found = {
            row["document"]: row
            for row in conn.execute(select(db.documents)).mappings()
        }
    assert found["policy_wording"]["version"] == "2026.1"
    assert found["claims_manual"]["version"] == "2026.2"
    assert json.loads(found["claims_manual"]["source"])["owner"] == (
        "Head of claims operations"
    )
    assert found["claims_manual"]["text"].startswith("# UnderCover Claims Handling")
    assert "reviewed:" not in found["policy_wording"]["text"]


def test_the_policy_wording_comes_from_the_documents_table(client):
    text = client.get("/api/policy-wording", headers=as_handler()).json()["text"]
    assert text.startswith("# UnderCover Travel Insurance: Policy Wording")
    assert "---" not in text.splitlines()[0]


def test_the_documents_routes_are_gone(client):
    assert client.get("/api/documents/search/giraffes").status_code == 404
    assert client.get("/api/documents/claims_manual/sections/7").status_code == 404
