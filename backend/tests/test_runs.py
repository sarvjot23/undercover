import pytest

from backend.routes import runs as run_routes


@pytest.fixture(autouse=True)
def no_agent(monkeypatch):
    """Start runs without the queue agent; the tests play its part."""
    monkeypatch.setattr(run_routes.queue_agent, "run", lambda run_id: None)


def start(client, cap=2):
    return client.post("/api/runs", json={"cap": cap}).json()


def decide(client, claim_id):
    client.post(f"/api/claims/{claim_id}/start")
    client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": "refer",
            "payout": 0,
            "reasons": "Needs a handler.",
            "policy_section": "11. How to claim",
        },
    )


def test_no_run_yet(client):
    assert client.get("/api/runs/current").json() is None


def test_a_run_works_up_to_its_cap(client):
    run = start(client, cap=2)
    assert run["status"] == "running"
    assert run["total"] == 2
    assert run["claim_ids"] == []
    assert client.get("/api/runs/current").json()["run_id"] == run["run_id"]


def test_the_total_is_the_waiting_claims_when_fewer_than_the_cap(client):
    assert start(client, cap=100)["total"] == 25


def test_only_one_run_at_a_time(client):
    start(client)
    assert client.post("/api/runs", json={"cap": 2}).status_code == 409


def test_a_cap_must_be_at_least_one(client):
    assert client.post("/api/runs", json={"cap": 0}).status_code == 422


def test_the_to_do_list_is_stored(client):
    run_id = start(client)["run_id"]
    todos = [
        {"claim_id": "CLM-1005", "note": "Passport, $243", "status": "done"},
        {"claim_id": "CLM-1002", "note": "Baggage", "status": "left_for_handler"},
    ]
    client.put(f"/api/runs/{run_id}/todos", json={"todos": todos})
    assert client.get("/api/runs/current").json()["todos"] == todos


def test_claims_are_taken_in_the_agents_order_within_the_cap(client):
    run_id = start(client)["run_id"]
    taken = client.post(f"/api/runs/{run_id}/claims/CLM-1020").json()
    assert taken["position"] == 1
    client.post(f"/api/runs/{run_id}/claims/CLM-1003")
    refused = client.post(f"/api/runs/{run_id}/claims/CLM-1001")
    assert refused.status_code == 409
    assert "capped at 2" in refused.json()["detail"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["claim_ids"] == ["CLM-1020", "CLM-1003"]


def test_a_retry_keeps_its_place(client):
    run_id = start(client)["run_id"]
    client.post(f"/api/runs/{run_id}/claims/CLM-1020")
    client.post(f"/api/runs/{run_id}/claims/CLM-1003")
    again = client.post(f"/api/runs/{run_id}/claims/CLM-1020")
    assert again.json()["position"] == 1


def test_only_a_waiting_claim_is_taken(client):
    run_id = start(client)["run_id"]
    decide(client, "CLM-1001")
    assert client.post(f"/api/runs/{run_id}/claims/CLM-1001").status_code == 409


def test_finishing_is_refused_while_a_claim_within_the_cap_waits(client):
    run_id = start(client)["run_id"]
    client.post(f"/api/runs/{run_id}/claims/CLM-1001")
    decide(client, "CLM-1001")
    refused = client.post(f"/api/runs/{run_id}/finish", json={"summary": "Done."})
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "These claims are still waiting: CLM-1008. Work them first"
    )
    client.post(f"/api/runs/{run_id}/claims/CLM-1002")
    decide(client, "CLM-1002")
    finished = client.post(f"/api/runs/{run_id}/finish", json={"summary": "Done."})
    assert finished.json()["status"] == "finished"
    assert finished.json()["summary"] == "Done."


def test_finishing_is_refused_while_a_failed_claim_waits_for_its_retry(client):
    run_id = start(client, cap=1)["run_id"]
    client.post(f"/api/runs/{run_id}/claims/CLM-1001")
    client.post("/api/claims/CLM-1001/start")
    client.post("/api/claims/CLM-1001/fail", json={"reason": "Timed out"})
    refused = client.post(f"/api/runs/{run_id}/finish", json={"summary": "Done."})
    assert "CLM-1001" in refused.json()["detail"]


def test_a_failed_run_sends_its_claims_back_to_the_queue(client):
    run_id = start(client)["run_id"]
    client.post(f"/api/runs/{run_id}/claims/CLM-1001")
    client.post("/api/claims/CLM-1001/start")
    failed = client.post(f"/api/runs/{run_id}/fail", json={"reason": "Broke"})
    assert failed.json()["status"] == "failed"
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"
    late = client.put(f"/api/runs/{run_id}/todos", json={"todos": []})
    assert late.status_code == 409


def test_an_unknown_run(client):
    assert client.get("/api/runs/99").status_code == 404
    assert client.post("/api/runs/99/claims/CLM-1001").status_code == 404
