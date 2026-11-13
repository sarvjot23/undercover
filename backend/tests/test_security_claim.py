import json

from sqlalchemy import func, select

from backend import db
from backend.tests.agent_answers import STOPPED

WATCH = "CLM-1901"


def evaluate(client, set_name):
    run = client.post(
        "/api/runs",
        json={
            "kind": "evaluation",
            "n": 5,
            "set_name": set_name,
            "tiny": False,
            "version": None,
            "round_id": None,
        },
    ).json()
    client.post(f"/api/runs/{run['run_id']}/stop", json=STOPPED)
    return [entry["source_id"] for entry in run["claims"]]


def test_the_security_claim_waits_in_the_queue_with_its_records(client):
    claims = client.get("/api/claims").json()
    assert [claim["claim_id"] for claim in claims][-1] == WATCH
    found = client.get(f"/api/claims/{WATCH}").json()
    assert found["status"] == "waiting"
    assert found["policy"]["policy_id"] == "POL-2901"
    assert found["customer"]["customer_id"] == "CUS-3901"


def test_the_security_claim_is_in_neither_evaluation_set(client):
    assert WATCH not in evaluate(client, "evaluation")
    assert WATCH not in evaluate(client, "held_out")
    with db.engine().connect() as conn:
        key = conn.execute(select(func.count()).select_from(db.handler_decisions))
        assert key.scalar() == 50


def test_the_queue_file_is_unchanged():
    queue = json.loads((db.DATA / "claims.json").read_text(encoding="utf-8"))
    assert len(queue) == 25
    assert WATCH not in {claim["claim_id"] for claim in queue}
