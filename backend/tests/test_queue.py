import pytest
from fastapi.testclient import TestClient

from backend import main


@pytest.fixture(autouse=True)
def idle_queue():
    main.queue_run.update(running=False, claim_ids=[], done=0, current=None)


def stub_agent(client: TestClient, runs: list[str], fail: str = ""):
    """Decide each claim the way the agent would, through the API."""

    def run(claim_id, thread_id):
        runs.append(claim_id)
        client.post(f"/api/claims/{claim_id}/start")
        if claim_id == fail:
            client.post(f"/api/claims/{claim_id}/fail", json={"reason": "down"})
            raise RuntimeError("model down")
        client.post(
            f"/api/claims/{claim_id}/decision",
            json={
                "decision": "refer",
                "payout": 0,
                "reasons": "Needs a handler.",
                "policy_section": "11. How to claim",
            },
        )

    return run


def test_queue_run_decides_every_waiting_claim_in_order(client, monkeypatch):
    runs: list[str] = []
    monkeypatch.setattr(main.agent, "run", stub_agent(client, runs))
    started = client.post("/api/queue/run").json()
    assert started["running"] is True
    assert len(started["claim_ids"]) == 25

    submitted = {
        claim["claim_id"]: claim["submitted_on"]
        for claim in client.get("/api/claims").json()
    }
    assert runs == sorted(
        submitted, key=lambda claim_id: (submitted[claim_id], claim_id)
    )
    assert {claim["status"] for claim in client.get("/api/claims").json()} == {
        "decided"
    }
    assert client.get("/api/queue/run").json() == {
        "running": False,
        "claim_ids": started["claim_ids"],
        "done": 25,
        "current": None,
    }


def test_queue_run_skips_claims_no_longer_waiting(client, monkeypatch):
    runs: list[str] = []
    monkeypatch.setattr(main.agent, "run", stub_agent(client, runs))
    client.post("/api/claims/CLM-1001/start")
    main.work_through(["CLM-1001", "CLM-1002"])
    assert runs == ["CLM-1002"]


def test_queue_run_carries_on_after_a_failed_run(client, monkeypatch):
    runs: list[str] = []
    monkeypatch.setattr(main.agent, "run", stub_agent(client, runs, fail="CLM-1001"))
    main.work_through(["CLM-1001", "CLM-1002"])
    assert runs == ["CLM-1001", "CLM-1002"]
    statuses = {c["claim_id"]: c["status"] for c in client.get("/api/claims").json()}
    assert statuses["CLM-1001"] == "waiting"
    assert statuses["CLM-1002"] == "decided"


def test_only_one_queue_run_at_a_time(client):
    main.queue_run.update(running=True)
    assert client.post("/api/queue/run").status_code == 409
