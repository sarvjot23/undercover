import pytest

from backend import agent_service, scoring
from backend.tests.signing import as_handler

TINY = ["CLM-1007", "CLM-1015", "CLM-1017", "CLM-1020", "CLM-1021"]
HELD_OUT_TINY = ["CLM-1104", "CLM-1106", "CLM-1110", "CLM-1112", "CLM-1114"]


def evaluate(client, set_name="evaluation", tiny=True):
    return client.post(
        "/api/runs",
        json={
            "kind": "evaluation",
            "n": 5,
            "set_name": set_name,
            "tiny": tiny,
            "model": "openai/gpt-6-luna",
            "reasoning": "low",
        },
    ).json()


def decide(client, claim_id, decision, payout):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": f"{claim_id}-t"})
    client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "reasons": "The wording settles it.",
            "policy_section": "3. Trip Delay",
        },
    )


def test_an_evaluation_works_copies_of_its_set_with_new_ids(client):
    run = evaluate(client)
    ids = [entry["claim_id"] for entry in run["claims"]]
    assert ids == [f"EV{run['run_id']}-{claim_id}" for claim_id in TINY]
    assert [entry["source_id"] for entry in run["claims"]] == TINY
    assert run["set_name"] == "evaluation"
    assert run["tiny"] is True
    assert (run["n"], run["model"], run["reasoning"]) == (5, "openai/gpt-6-luna", "low")


def test_the_whole_set_and_the_held_out_set(client):
    whole = evaluate(client, tiny=False)
    assert whole["total"] == 25
    client.post(f"/api/runs/{whole['run_id']}/stop")
    held_out = evaluate(client, "held_out")
    assert [e["source_id"] for e in held_out["claims"]] == HELD_OUT_TINY


def test_copies_stay_out_of_the_queue(client):
    before = client.get("/api/claims").json()
    run = evaluate(client)
    for entry in run["claims"]:
        decide(client, entry["claim_id"], "refer", 0)
    assert client.get("/api/claims").json() == before


def test_get_claim_on_a_copy_holds_its_new_id_and_nothing_of_the_answer_key(client):
    copy_id = evaluate(client)["claims"][0]["claim_id"]
    response = client.get(f"/api/claims/{copy_id}")
    found = response.json()
    assert found["claim_id"] == copy_id
    assert "evaluation_id" not in found
    for field in ("handler_id", "reason", "tiny", "over_approval_limit", "difficulty"):
        assert f'"{field}"' not in response.text
    assert "The carrier canceled" not in response.text
    assert client.get(f"/api/claims/{copy_id}/standing").json()["evaluation_id"]


def test_a_sign_off_on_a_copy_is_refused(client):
    copy_id = evaluate(client)["claims"][4]["claim_id"]
    decide(client, copy_id, "approve", 825)
    refused = client.post(f"/api/claims/{copy_id}/sign-off", headers=as_handler())
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"Claim {copy_id} is a copy for an evaluation"


def test_the_measures_match_ones_worked_out_by_hand():
    key = {
        "A": {"decision": "approve", "payout": 420.0},
        "B": {"decision": "approve", "payout": 420.0},
        "C": {"decision": "approve", "payout": 300.0},
        "D": {"decision": "decline", "payout": 0.0},
        "E": {"decision": "approve", "payout": 100.0},
        "F": {"decision": "decline", "payout": 0.0},
    }
    answers = [
        ("A", "approve", 420.5),
        ("B", "approve", 500.0),
        ("C", "decline", 0.0),
        ("D", "approve", 250.0),
        ("E", "refer", 0.0),
        ("F", None, None),
    ]
    entries = [
        {
            "source_id": source,
            "decision": decision,
            "payout": payout,
            "cost": 0.01 * (number + 1),
            "seconds": 10.0 * (number + 1),
        }
        for number, (source, decision, payout) in enumerate(answers)
    ]
    rows = scoring.score_rows(entries, key)
    assert [row["right"] for row in rows] == [True, False, False, False, False, False]
    assert [row["mistake_cost"] for row in rows] == [0.5, 80.0, 1500, 250.0, 50, 50]
    assert rows[5]["agent_decision"] == "refer"
    scores = scoring.run_scores(rows, 75.0)
    assert scores["decision_accuracy"] == pytest.approx(2 / 6)
    assert scores["accuracy"] == pytest.approx(1 / 6)
    assert scores["cost_of_mistakes"] == pytest.approx(1930.5)
    assert scores["straight_through"] == pytest.approx(4 / 6)
    assert scores["cost"] == pytest.approx(0.21)
    assert scores["cost_per_claim"] == pytest.approx(0.035)
    assert scores["seconds_per_claim"] == pytest.approx(35.0)
    assert scores["seconds"] == 75.0


def test_a_finished_evaluation_is_scored_from_its_own_records(client):
    run = evaluate(client)
    copies = {entry["source_id"]: entry["claim_id"] for entry in run["claims"]}
    decide(client, copies["CLM-1007"], "approve", 50)
    client.post(f"/api/claims/{copies['CLM-1007']}/payment", json={"amount": 50})
    decide(client, copies["CLM-1015"], "decline", 0)
    decide(client, copies["CLM-1017"], "refer", 0)
    decide(client, copies["CLM-1020"], "approve", 300)
    client.post(f"/api/claims/{copies['CLM-1020']}/payment", json={"amount": 300})
    client.post(f"/api/runs/{run['run_id']}/finish")

    found = client.get(f"/api/evaluations/{run['run_id']}").json()
    by_source = {row["source_id"]: row for row in found["claims"]}
    assert by_source["CLM-1020"]["handler_payout"] == 240.0
    assert by_source["CLM-1020"]["agent_payout"] == 300.0
    assert by_source["CLM-1020"]["mistake_cost"] == 60.0
    assert by_source["CLM-1021"]["agent_decision"] == "refer"
    assert by_source["CLM-1021"]["decision"] is None
    scores = found["scores"]
    assert scores["decision_accuracy"] == pytest.approx(4 / 5)
    assert scores["accuracy"] == pytest.approx(3 / 5)
    assert scores["cost_of_mistakes"] == pytest.approx(110.0)
    assert scores["straight_through"] == pytest.approx(3 / 5)

    listed = client.get("/api/evaluations").json()
    assert [e["run_id"] for e in listed] == [run["run_id"]]
    assert listed[0]["scores"] == scores
    assert "claims" not in listed[0]


def test_a_stopped_evaluation_shows_as_stopped_with_no_measures(client):
    run = evaluate(client)
    decide(client, run["claims"][0]["claim_id"], "refer", 0)
    client.post(f"/api/runs/{run['run_id']}/stop")
    found = client.get(f"/api/evaluations/{run['run_id']}").json()
    assert found["status"] == "stopped"
    assert found["scores"] is None
    assert found["claims"][0]["agent_decision"] == "refer"


def test_evaluations_are_listed_newest_first(client):
    first = evaluate(client)
    client.post(f"/api/runs/{first['run_id']}/finish")
    second = evaluate(client, "held_out")
    client.post(f"/api/runs/{second['run_id']}/stop")
    listed = client.get("/api/evaluations").json()
    assert [e["run_id"] for e in listed] == [second["run_id"], first["run_id"]]


def test_a_dispatch_is_not_an_evaluation(client):
    run_id = client.post(
        "/api/runs",
        json={
            "kind": "dispatch",
            "n": 3,
            "set_name": None,
            "tiny": False,
            "model": "m",
            "reasoning": "low",
        },
    ).json()["run_id"]
    assert client.get(f"/api/evaluations/{run_id}").status_code == 404


def test_an_evaluation_is_asked_of_the_agents_service(client, monkeypatch):
    asked = []
    monkeypatch.setattr(
        agent_service, "ask", lambda path, body: asked.append((path, body)) or 202
    )
    body = {"set_name": "held_out", "tiny": True, "n": 5}
    assert (
        client.post("/api/evaluations", json=body, headers=as_handler()).status_code
        == 202
    )
    assert asked == [("/evaluations", body)]
