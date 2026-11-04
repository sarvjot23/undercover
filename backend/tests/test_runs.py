import pytest

from backend import agent_service

DISPATCH = {
    "kind": "dispatch",
    "n": 3,
    "set_name": None,
    "tiny": False,
    "model": "openai/gpt-6-luna",
    "reasoning": "low",
}
EVALUATION = {**DISPATCH, "kind": "evaluation", "set_name": "evaluation", "tiny": True}


def create(client, record=DISPATCH):
    return client.post("/api/runs", json=record)


def begin(client, claim_id):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": f"{claim_id}-t"})


def decide(client, claim_id, decision="refer", payout=0.0):
    begin(client, claim_id)
    client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "reasons": "The wording settles it.",
            "policy_section": "11. How to claim",
        },
    )


def test_no_run_yet(client):
    assert client.get("/api/runs/current").json() is None
    assert client.get("/api/runs/running").json() is None


def test_a_dispatch_takes_the_claims_in_progress_then_the_oldest_waiting(client):
    begin(client, "CLM-1020")
    decide(client, "CLM-1003")
    run = create(client).json()
    claims = client.get("/api/claims").json()
    waiting = sorted(
        (claim["submitted_on"], claim["claim_id"])
        for claim in claims
        if claim["status"] == "waiting"
    )
    ids = [entry["claim_id"] for entry in run["claims"]]
    assert ids == ["CLM-1020", *[claim_id for _, claim_id in waiting]]
    assert "CLM-1003" not in ids
    assert run["total"] == 24
    assert run["status"] == "running"
    assert run["kind"] == "dispatch"
    assert run["n"] == 3
    assert (run["model"], run["reasoning"]) == ("openai/gpt-6-luna", "low")
    assert run["summary"] is None


def test_a_dispatch_never_takes_an_evaluations_copies(client):
    evaluation = create(client, EVALUATION).json()
    client.post(f"/api/runs/{evaluation['run_id']}/stop")
    dispatch = create(client).json()
    ids = [entry["claim_id"] for entry in dispatch["claims"]]
    assert len(ids) == 25
    assert not any(claim_id.startswith("EV") for claim_id in ids)


@pytest.mark.parametrize("second", [DISPATCH, EVALUATION])
def test_only_one_run_at_a_time_of_either_kind(client, second):
    first = create(client).json()
    refused = create(client, second)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "A dispatch or evaluation is already running"
    assert client.get("/api/runs/running").json()["run_id"] == first["run_id"]


def test_a_finished_run_makes_way_for_the_next(client):
    run_id = create(client).json()["run_id"]
    finished = client.post(f"/api/runs/{run_id}/finish").json()
    assert finished["status"] == "finished"
    assert finished["finished_at"]
    assert client.get("/api/runs/running").json() is None
    assert create(client).status_code == 200


def test_a_stopped_run_shows_as_stopped(client):
    run_id = create(client).json()["run_id"]
    assert client.post(f"/api/runs/{run_id}/stop").json()["status"] == "stopped"
    assert client.get("/api/runs/current").json()["status"] == "stopped"
    again = client.post(f"/api/runs/{run_id}/finish")
    assert again.status_code == 409
    assert again.json()["detail"] == f"Run {run_id} is stopped"


def test_the_summary_is_built_from_the_records(client):
    run_id = create(client).json()["run_id"]
    decide(client, "CLM-1001", "approve", 420.0)
    client.post("/api/claims/CLM-1001/payment", json={"amount": 420.0})
    decide(client, "CLM-1008", "approve", 2240.0)
    decide(client, "CLM-1002", "decline")
    decide(client, "CLM-1003")
    begin(client, "CLM-1004")
    client.post("/api/claims/CLM-1004/fail", json={"reason": "Broke"})
    client.post("/api/claims/CLM-1004/start", json={"thread_id": "CLM-1004-u"})
    client.post("/api/claims/CLM-1004/fail", json={"reason": "Broke again"})
    begin(client, "CLM-1005")
    finished = client.post(f"/api/runs/{run_id}/finish").json()
    summary = finished["summary"]
    assert (summary["approved"], summary["declined"], summary["referred"]) == (2, 1, 1)
    assert summary["awaiting_sign_off"] == [{"claim_id": "CLM-1008", "payout": 2240.0}]
    assert summary["left_for_handler"] == ["CLM-1004"]
    assert summary["in_progress"] == ["CLM-1005"]


def test_a_run_adds_up_its_cost_and_time(client):
    run_id = create(client).json()["run_id"]
    for key, cost in (("gen-1", 0.002), ("gen-2", 0.003)):
        client.post(
            "/api/claims/CLM-1001/usage",
            json={
                "run_id": run_id,
                "model": "openai/gpt-6-luna",
                "input_tokens": 1000,
                "output_tokens": 50,
                "cost": cost,
                "key": key,
            },
        )
    for started, finished in (("09:00:00", "09:00:20"), ("09:01:00", "09:01:05")):
        client.post(
            "/api/claims/CLM-1001/work",
            json={
                "run_id": run_id,
                "started": f"2026-11-04T{started}+00:00",
                "finished": f"2026-11-04T{finished}+00:00",
            },
        )
    client.post(
        "/api/claims/CLM-1002/work",
        json={
            "run_id": None,
            "started": "2026-11-04T09:00:00+00:00",
            "finished": "2026-11-04T09:09:00+00:00",
        },
    )
    run = client.get(f"/api/runs/{run_id}").json()
    entry = next(e for e in run["claims"] if e["claim_id"] == "CLM-1001")
    assert entry["cost"] == pytest.approx(0.005)
    assert entry["seconds"] == 25.0
    assert entry["started"] == "2026-11-04T09:00:00+00:00"
    assert run["cost"] == pytest.approx(0.005)
    assert run["seconds"] == 25.0
    assert run["elapsed"] >= 0


def test_usage_and_work_need_a_claim(client):
    work = {
        "run_id": None,
        "started": "2026-11-04T09:00:00Z",
        "finished": "2026-11-04T09:00:01Z",
    }
    assert client.post("/api/claims/CLM-9999/work", json=work).status_code == 404


def test_only_an_evaluation_has_a_set(client):
    assert create(client, {**DISPATCH, "set_name": "evaluation"}).status_code == 422
    assert create(client, {**EVALUATION, "set_name": None}).status_code == 422


def test_an_unknown_run(client):
    assert client.get("/api/runs/99").status_code == 404
    assert client.post("/api/runs/99/finish").status_code == 404


def test_a_dispatch_is_asked_of_the_agents_service_with_n(client, monkeypatch):
    asked = []
    monkeypatch.setattr(
        agent_service, "ask", lambda path, body: asked.append((path, body)) or 202
    )
    started = client.post("/api/dispatches", json={"n": 5})
    assert started.status_code == 202
    assert asked == [("/dispatches", {"n": 5})]


def test_a_dispatch_refused_by_the_service_is_refused(client, monkeypatch):
    monkeypatch.setattr(agent_service, "ask", lambda path, body: 409)
    refused = client.post("/api/dispatches", json={"n": 5})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "A dispatch or evaluation is already running"


def test_a_dispatch_needs_the_agents_service(client, monkeypatch):
    monkeypatch.setattr(agent_service, "ask", lambda path, body: None)
    refused = client.post("/api/dispatches", json={"n": 5})
    assert refused.status_code == 503
    assert refused.json()["detail"] == "The agent's service isn't running"


@pytest.mark.parametrize("n", [0, 26])
def test_n_is_from_1_to_25(client, n):
    assert client.post("/api/dispatches", json={"n": n}).status_code == 422
