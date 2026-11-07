import json

import pytest
from sqlalchemy import select

from backend import agent_service, db, evaluations, rounds
from backend.tests.signing import MARCUS, as_handler

RUN = {"kind": "evaluation", "n": 25, "tiny": False}
CHANGE = {
    "instructions": "Refer a claim with a missing receipt.",
    "model": "openai/gpt-6-luna",
    "reasoning": "medium",
    "reason": "Two misses had no receipt.",
}


@pytest.fixture
def small(monkeypatch):
    """Evaluations of the first two claims of each set, so the tests run quickly."""
    original = evaluations.source_claims
    monkeypatch.setattr(
        evaluations,
        "source_claims",
        lambda conn, set_name, tiny: original(conn, set_name, tiny)[:2],
    )


def start(client, handler_id="HND-01"):
    return client.post("/api/rounds/records", json={"handler_id": handler_id}).json()


def key(set_name):
    with db.engine().connect() as conn:
        query = select(db.handler_decisions).where(
            db.handler_decisions.c.set_name == set_name
        )
        return {row["claim_id"]: dict(row) for row in conn.execute(query).mappings()}


def evaluate(client, round_id, version, set_name, right):
    """An evaluation for a round: every copy decided as the handler did, or left."""
    body = {**RUN, "set_name": set_name, "version": version, "round_id": round_id}
    run = client.post("/api/runs", json=body).json()
    answers = key(set_name)
    for entry in run["claims"]:
        if right:
            expected = answers[entry["source_id"]]
            client.post(
                f"/api/claims/{entry['claim_id']}/start", json={"thread_id": "t"}
            )
            client.post(
                f"/api/claims/{entry['claim_id']}/decision",
                json={
                    "decision": expected["decision"],
                    "payout": expected["payout"],
                    "reasons": "As the handler decided.",
                    "policy_section": "3. Trip Delay",
                },
            )
    client.post(f"/api/runs/{run['run_id']}/finish")
    return run


def evaluate_version(client, round_id, version, right):
    for set_name in ("evaluation", "held_out", "held_out"):
        evaluate(client, round_id, version, set_name, right)


def propose_and_approve(client, round_id):
    client.post(f"/api/rounds/{round_id}/proposals/change", json=CHANGE)
    client.post(
        f"/api/rounds/{round_id}/decisions",
        json={"decision": "approve", "message": "", "handler_id": "HND-01"},
    )


def current(client):
    return client.get("/api/configuration/current").json()["version"]


def test_a_round_opens_on_a_copy_of_the_settings_and_the_latest_recipe(client):
    found = start(client)
    assert found["status"] == "working"
    assert found["recipe_version"] == 1
    assert found["version_before"] == 1
    assert found["thread_id"].startswith(f"round-{found['round_id']}-")
    assert found["settings"]["round_spending_limit"] == 0.5
    refused = client.post("/api/rounds/records", json={"handler_id": "HND-01"})
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"Round {found['round_id']} is open"


def test_the_current_version_needs_its_first_evaluations(client, small):
    round_id = start(client)["round_id"]
    path = f"/api/rounds/{round_id}/first-evaluations"
    assert client.get(path).json() == {
        "version": 1,
        "sets": ["evaluation", "held_out", "held_out"],
    }
    evaluate(client, round_id, None, "held_out", right=False)
    evaluate(client, None, None, "evaluation", right=False)
    assert client.get(path).json()["sets"] == ["evaluation", "held_out"]


def test_a_proposal_changes_nothing_until_it_is_approved(client):
    round_id = start(client)["round_id"]
    client.post(f"/api/rounds/{round_id}/proposals/change", json=CHANGE)
    waiting = client.get(f"/api/rounds/{round_id}").json()
    assert (waiting["status"], waiting["stage"]) == ("waiting", "change_waiting")
    assert waiting["proposal"]["model_before"] == "openai/gpt-6-luna"
    assert waiting["proposal"]["reasoning_before"] == "low"
    assert {"kind": "add", "text": CHANGE["instructions"]} in waiting["proposal"][
        "diff"
    ]
    assert (
        len(client.get("/api/configuration/versions", headers=as_handler()).json()) == 1
    )

    client.post(
        f"/api/rounds/{round_id}/decisions",
        json={"decision": "approve", "message": "", "handler_id": "HND-01"},
    )
    approved = client.get(f"/api/rounds/{round_id}").json()
    assert approved["version_tried"] == 2
    assert approved["status"] == "working"
    assert approved["events"][0]["handler_id"] == "HND-01"
    assert approved["events"][0]["decision"] == "approve"
    assert current(client) == 1


def test_a_rejection_records_who_and_why_and_saves_nothing(client):
    round_id = start(client)["round_id"]
    client.post(f"/api/rounds/{round_id}/proposals/change", json=CHANGE)
    client.post(
        f"/api/rounds/{round_id}/decisions",
        json={"decision": "reject", "message": "Too broad.", "handler_id": "HND-01"},
    )
    found = client.get(f"/api/rounds/{round_id}").json()
    assert found["version_tried"] is None
    assert found["proposal"] is None
    assert found["events"][0]["message"] == "Too broad."
    again = client.post(
        f"/api/rounds/{round_id}/decisions",
        json={"decision": "approve", "message": "", "handler_id": "HND-01"},
    )
    assert again.status_code == 409


def test_a_recipe_approved_becomes_the_next_rounds_recipe(client):
    round_id = start(client)["round_id"]
    client.post(
        f"/api/rounds/{round_id}/proposals/recipe",
        json={"recipe": "1. Read the results.\n2. Think.", "reason": "Shorter."},
    )
    proposal = client.get(f"/api/rounds/{round_id}").json()["proposal"]
    assert {"kind": "add", "text": "2. Think."} in proposal["diff"]
    client.post(
        f"/api/rounds/{round_id}/decisions",
        json={"decision": "approve", "message": "", "handler_id": "HND-01"},
    )
    client.post(f"/api/rounds/{round_id}/finish")
    recipes = client.get("/api/recipes", headers=as_handler()).json()
    assert recipes[0]["version"] == 2
    assert recipes[0]["approved_by"] == "HND-01"
    following = start(client)
    assert following["recipe_version"] == 2
    instructions = client.get(f"/api/rounds/{following['round_id']}/instructions")
    assert "2. Think." in instructions.json()["instructions"]
    assert "never names a claim" in instructions.json()["instructions"]


def test_a_proposal_outside_the_models_allowed_is_refused(client):
    round_id = start(client)["round_id"]
    refused = client.post(
        f"/api/rounds/{round_id}/proposals/change",
        json={**CHANGE, "model": "someone/else"},
    )
    assert refused.status_code == 422


def test_a_better_version_is_kept_with_the_rounds_own_settings(client, small):
    round_id = start(client)["round_id"]
    evaluate_version(client, round_id, None, right=False)
    # The settings change while the round is open: it keeps its own copy.
    settings = client.get("/api/settings").json()["settings"]
    settings["objectives"]["accuracy"] = 1.0
    settings["objectives"]["grade"] = 3.0
    client.put("/api/settings", json=settings, headers=as_handler())

    propose_and_approve(client, round_id)
    evaluate_version(client, round_id, 2, right=True)
    judged = client.post(
        f"/api/rounds/{round_id}/verdict", json={"unaffordable": False}
    ).json()
    assert judged["verdict"] == "kept"
    assert judged["why"] == "accuracy and the grade improved by more than the noise"
    assert judged["before"]["grade"] == 0.0
    assert judged["after"]["accuracy"] == 1.0
    assert judged["settings"]["objectives"]["accuracy"] == 0.6
    assert current(client) == 2

    # Stopped after its verdict, the round keeps the version.
    client.post(f"/api/rounds/{round_id}/stop", headers=as_handler())
    assert current(client) == 2


def test_a_round_stopped_before_its_verdict_leaves_the_current_version(client):
    round_id = start(client)["round_id"]
    propose_and_approve(client, round_id)
    stopped = client.post(f"/api/rounds/{round_id}/stop", headers=as_handler())
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["verdict"] == "rolled_back"
    assert current(client) == 1
    refused = client.post(
        f"/api/rounds/{round_id}/progress",
        json={"stage": "evaluations", "progress": "1 of 3"},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"Round {round_id} is stopped"


def test_a_version_whose_evaluations_were_stopped_is_rolled_back(client, small):
    round_id = start(client)["round_id"]
    evaluate_version(client, round_id, None, right=False)
    propose_and_approve(client, round_id)
    evaluate(client, round_id, 2, "evaluation", right=True)
    body = {**RUN, "set_name": "held_out", "version": 2, "round_id": round_id}
    run = client.post("/api/runs", json=body).json()
    client.post(f"/api/runs/{run['run_id']}/stop")
    judged = client.post(
        f"/api/rounds/{round_id}/verdict", json={"unaffordable": False}
    ).json()
    assert judged["verdict"] == "rolled_back"
    assert judged["why"] == "its evaluations didn't all finish"
    assert current(client) == 1


def test_a_version_the_round_cant_afford_is_rolled_back(client):
    round_id = start(client)["round_id"]
    propose_and_approve(client, round_id)
    judged = client.post(
        f"/api/rounds/{round_id}/verdict", json={"unaffordable": True}
    ).json()
    assert judged["verdict"] == "rolled_back"
    assert judged["why"] == "the round couldn't afford to evaluate it"


def test_the_improvers_view_holds_nothing_of_the_held_out_set_but_its_scores(
    client, small
):
    round_id = start(client)["round_id"]
    evaluate_version(client, round_id, None, right=False)
    view = client.get(f"/api/rounds/{round_id}/view").json()
    text = json.dumps(view)
    assert view["scores"]["held_out"]["runs"] == 2
    assert view["current_version"]["version"] == 1
    assert view["evaluation_set"]["wrong"]
    first = view["evaluation_set"]["wrong"][0]
    assert first["handler"]["reason"]
    assert first["judge"]["letter"] == "F"
    for claim_id, answer in key("held_out").items():
        assert claim_id not in text
        assert answer["reason"] not in text
    assert view["noise"]["accuracy"] == 0.1
    assert view["spending_limit_left"] == 0.5
    assert len(view["models_allowed"]) == 3
    assert "tolerance" in view["rule"]


def test_spending_counts_the_improver_the_agents_and_the_judge(client, small):
    round_id = start(client)["round_id"]
    run = evaluate(client, round_id, None, "evaluation", right=True)
    client.post(
        f"/api/claims/{run['claims'][0]['claim_id']}/usage",
        json={
            "run_id": run["run_id"],
            "model": "openai/gpt-6-luna",
            "input_tokens": 10,
            "output_tokens": 1,
            "cost": 0.004,
            "key": "gen-claim",
        },
    )
    client.post(
        f"/api/rounds/{round_id}/usage",
        json={
            "model": "openai/gpt-6-luna",
            "input_tokens": 10,
            "output_tokens": 1,
            "cost": 0.01,
            "key": "gen-improver",
        },
    )
    found = client.get(f"/api/rounds/{round_id}/spending").json()
    # Two copies graded by the stand-in judge at $0.0001 each.
    assert found["spent"] == pytest.approx(0.0142)
    assert found["left"] == pytest.approx(0.5 - 0.0142)
    assert found["estimate"] is None

    propose_and_approve(client, round_id)
    # The run's cost per claim, $0.002, times 75 claims.
    estimate = client.get(f"/api/rounds/{round_id}/spending").json()["estimate"]
    assert estimate == pytest.approx(0.15)


def test_a_model_with_no_runs_is_estimated_from_the_current_one(client, small):
    round_id = start(client)["round_id"]
    run = evaluate(client, round_id, None, "evaluation", right=True)
    client.post(
        f"/api/claims/{run['claims'][0]['claim_id']}/usage",
        json={
            "run_id": run["run_id"],
            "model": "openai/gpt-6-luna",
            "input_tokens": 10,
            "output_tokens": 1,
            "cost": 0.004,
            "key": "gen-claim",
        },
    )
    client.post(
        f"/api/rounds/{round_id}/proposals/change",
        json={**CHANGE, "model": "google/gemini-3.5-flash-lite", "reasoning": "low"},
    )
    client.post(
        f"/api/rounds/{round_id}/decisions",
        json={"decision": "approve", "message": "", "handler_id": "HND-01"},
    )
    estimate = client.get(f"/api/rounds/{round_id}/spending").json()["estimate"]
    # Flash Lite's output price is 5 times Luna's, its input price 3 times.
    assert estimate == pytest.approx(75 * 0.002 * 5)


def test_rounds_are_listed_newest_first(client):
    first = start(client)["round_id"]
    client.post(f"/api/rounds/{first}/finish")
    second = start(client)["round_id"]
    listed = client.get("/api/rounds", headers=as_handler()).json()
    assert [found["round_id"] for found in listed] == [second, first]
    assert client.get("/api/rounds/open").json()["round_id"] == second


def test_a_start_is_asked_of_the_service_with_the_handler(client, monkeypatch):
    asked = []
    monkeypatch.setattr(
        agent_service,
        "ask",
        lambda path, body: asked.append((path, body)) or agent_service.Answer(202, ""),
    )
    assert client.post("/api/rounds", headers=as_handler()).status_code == 202
    assert asked == [("/rounds", {"handler_id": "HND-01"})]


def test_a_refusal_from_the_service_names_what_is_running(client, monkeypatch):
    refusal = agent_service.Answer(409, "Dispatch 7 is running")
    monkeypatch.setattr(agent_service, "ask", lambda path, body: refusal)
    round_id = start(client)["round_id"]
    client.post(f"/api/rounds/{round_id}/proposals/change", json=CHANGE)
    refused = client.post(
        f"/api/rounds/{round_id}/decision",
        json={"decision": "approve", "message": ""},
        headers=as_handler(),
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Dispatch 7 is running"
    assert client.get(f"/api/rounds/{round_id}").json()["events"] == []


def test_a_rejection_needs_a_reason(client):
    round_id = start(client)["round_id"]
    client.post(f"/api/rounds/{round_id}/proposals/change", json=CHANGE)
    refused = client.post(
        f"/api/rounds/{round_id}/decision",
        json={"decision": "reject", "message": "  "},
        headers=as_handler(),
    )
    assert refused.status_code == 422


def test_nothing_to_decide_is_refused(client):
    round_id = start(client)["round_id"]
    refused = client.post(
        f"/api/rounds/{round_id}/decision",
        json={"decision": "approve", "message": ""},
        headers=as_handler(),
    )
    assert refused.status_code == 409


@pytest.mark.parametrize(
    ("path", "body", "action"),
    [
        ("/api/rounds", None, "start a round"),
        ("/api/rounds/1/stop", None, "stop a round"),
        (
            "/api/rounds/1/decision",
            {"decision": "approve", "message": ""},
            "approve or reject the improver's proposals",
        ),
    ],
)
def test_marcus_can_do_nothing_with_a_round(client, path, body, action):
    start(client)
    refused = client.post(path, json=body, headers=as_handler(MARCUS))
    assert refused.status_code == 403
    assert refused.json()["detail"].endswith(f"so can't {action}")
    assert client.post(path, json=body).status_code == 401


def test_a_round_left_working_can_be_halted(client):
    round_id = start(client)["round_id"]
    assert client.post(f"/api/rounds/{round_id}/halt").json()["status"] == "stopped"
    with db.engine().connect() as conn:
        assert rounds.open_round(conn) is None
