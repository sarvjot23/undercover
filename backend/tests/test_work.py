import threading

import pytest
from sqlalchemy import select

from backend import agent_service, db, rounds, work
from backend.agent_service import Answer
from backend.tests.agent_answers import ACCEPTED
from backend.tests.signing import as_handler

LONG_AGO = "2000-01-01T00:00:00+00:00"
CHANGE = {
    "instructions": "Refer a claim with a missing receipt.",
    "model": "openai/gpt-6-luna",
    "reasoning": "medium",
    "reason": "Two misses had no receipt.",
}


@pytest.fixture
def asked(monkeypatch):
    """The agent takes everything it's asked, and the payloads are kept."""
    payloads = []
    monkeypatch.setattr(
        agent_service, "send", lambda payload: payloads.append(payload) or ACCEPTED
    )
    return payloads


def dispatch(client):
    return client.post("/api/dispatches", json={"n": 3}, headers=as_handler())


def evaluate(client):
    body = {"set_name": "evaluation", "tiny": True, "n": 3}
    return client.post("/api/evaluations", json=body, headers=as_handler())


def start_round(client):
    return client.post("/api/rounds", headers=as_handler())


def run(client, run_id):
    return client.get(f"/api/runs/{run_id}").json()


def a_round(client, round_id):
    return client.get(f"/api/rounds/{round_id}").json()


def gone_quiet(table, key, value):
    with db.engine().begin() as conn:
        conn.execute(
            table.update().where(table.c[key] == value).values(heard_at=LONG_AGO)
        )


@pytest.mark.parametrize(
    ("first", "going"),
    [(dispatch, "Dispatch"), (evaluate, "Evaluation"), (start_round, "Round")],
)
def test_a_second_start_is_refused_while_work_is_going(client, asked, first, going):
    started = first(client).json()
    for second in (dispatch, evaluate, start_round):
        refused = second(client)
        assert refused.status_code == 409
        number = started.get("run_id", started.get("round_id"))
        verb = "working" if going == "Round" else "running"
        assert refused.json()["detail"] == f"{going} {number} is {verb}"
    assert len(asked) == 1


def test_a_round_waiting_for_a_review_lets_a_dispatch_start(client, asked):
    round_id = start_round(client).json()["round_id"]
    client.post(f"/api/rounds/{round_id}/proposals/change", json=CHANGE)
    assert dispatch(client).status_code == 202


def test_two_starts_at_the_same_moment_only_one_goes_through(client, asked):
    answers = []
    ready = threading.Barrier(2)

    def start():
        ready.wait()
        answers.append(dispatch(client).status_code)

    starts = [threading.Thread(target=start) for _ in range(2)]
    for thread in starts:
        thread.start()
    for thread in starts:
        thread.join()
    assert sorted(answers) == [202, 409]
    with db.engine().connect() as conn:
        running = select(db.runs).where(db.runs.c.status == "running")
        assert len(conn.execute(running).all()) == 1


def test_a_start_after_a_run_went_quiet_stops_it_and_goes_ahead(client, asked):
    quiet = dispatch(client).json()["run_id"]
    gone_quiet(db.runs, "run_id", quiet)
    assert evaluate(client).status_code == 202
    stopped = run(client, quiet)
    assert (stopped["status"], stopped["stop_reason"]) == (
        "stopped",
        "The agent stopped answering",
    )


def test_a_round_gone_quiet_is_stopped_with_its_evaluation(client, asked):
    round_id = start_round(client).json()["round_id"]
    evaluation = client.post(
        "/api/runs",
        json={
            "kind": "evaluation",
            "n": 3,
            "set_name": "evaluation",
            "tiny": True,
            "version": 1,
            "round_id": round_id,
        },
    ).json()["run_id"]
    # The round's evaluation is never stopped on its own: the round's word covers it.
    gone_quiet(db.runs, "run_id", evaluation)
    assert dispatch(client).status_code == 409
    assert run(client, evaluation)["status"] == "running"

    gone_quiet(db.rounds, "round_id", round_id)
    assert dispatch(client).status_code == 202
    assert a_round(client, round_id)["stop_reason"] == "The agent stopped answering"
    assert run(client, evaluation)["stop_reason"] == "The agent stopped answering"


def test_work_the_agent_tells_about_is_not_quiet(client, asked):
    quiet = dispatch(client).json()["run_id"]
    gone_quiet(db.runs, "run_id", quiet)
    assert client.post(f"/api/runs/{quiet}/heard").status_code == 200
    assert dispatch(client).status_code == 409


def not_taken(monkeypatch, reason="The agent isn't running"):
    answer = Answer("not_taken", reason, {})
    monkeypatch.setattr(agent_service, "send", lambda payload: answer)


def test_a_dispatch_the_agent_didnt_take_is_stopped_with_the_reason(
    client, monkeypatch
):
    not_taken(monkeypatch)
    refused = dispatch(client)
    assert refused.status_code == 503
    assert refused.json()["detail"] == "The agent isn't running"
    latest = client.get("/api/runs/current", headers=as_handler()).json()
    assert (latest["status"], latest["stop_reason"]) == (
        "stopped",
        "The agent isn't running",
    )


def test_a_run_the_agent_refused_is_stopped_with_its_reason(client, monkeypatch):
    refusal = Answer("refused", "Run 1 is stopped", {})
    monkeypatch.setattr(agent_service, "send", lambda payload: refusal)
    assert dispatch(client).status_code == 409
    latest = client.get("/api/runs/current", headers=as_handler()).json()
    assert latest["stop_reason"] == "Run 1 is stopped"


def test_a_round_the_agent_didnt_take_is_stopped(client, monkeypatch):
    not_taken(monkeypatch)
    assert start_round(client).status_code == 503
    with db.engine().connect() as conn:
        assert rounds.open_round(conn) is None
        latest = conn.execute(select(db.rounds)).mappings().one()
    assert latest["stop_reason"] == "The agent isn't running"


def test_a_timeout_leaves_the_work_going(client, monkeypatch):
    unknown = Answer("unknown", agent_service.UNKNOWN, {})
    monkeypatch.setattr(agent_service, "send", lambda payload: unknown)
    answer = dispatch(client)
    assert answer.status_code == 504
    assert "Reload the page" in answer.json()["detail"]
    latest = client.get("/api/runs/current", headers=as_handler()).json()
    assert latest["status"] == "running"


def proposal_waiting(client, asked):
    round_id = start_round(client).json()["round_id"]
    client.post(f"/api/rounds/{round_id}/proposals/change", json=CHANGE)
    return round_id


def test_a_review_is_recorded_by_the_app_and_read_by_the_agent(client, asked):
    round_id = proposal_waiting(client, asked)
    reviewed = client.post(
        f"/api/rounds/{round_id}/decision",
        json={"decision": "reject", "message": "Too broad."},
        headers=as_handler(),
    )
    assert reviewed.status_code == 202
    payload = asked[-1]
    assert payload["operation"] == "carry_round_on"
    review = client.get(
        f"/api/rounds/{round_id}/reviews/{payload['proposal_id']}"
    ).json()
    assert review == {"decision": "reject", "message": "Too broad."}
    assert a_round(client, round_id)["status"] == "working"


def test_a_review_the_agent_didnt_take_is_undone(client, asked, monkeypatch):
    round_id = proposal_waiting(client, asked)
    not_taken(monkeypatch)
    refused = client.post(
        f"/api/rounds/{round_id}/decision",
        json={"decision": "approve", "message": ""},
        headers=as_handler(),
    )
    assert refused.status_code == 503
    found = a_round(client, round_id)
    assert (found["status"], found["stage"]) == ("waiting", "change_waiting")
    assert found["proposal"]["instructions"] == CHANGE["instructions"]
    assert found["version_tried"] is None
    assert found["events"] == []
    versions = client.get("/api/configuration/versions", headers=as_handler()).json()
    assert len(versions) == 1


def test_a_halted_round_stops_its_running_evaluation(client, asked):
    round_id = start_round(client).json()["round_id"]
    evaluation = client.post(
        "/api/runs",
        json={
            "kind": "evaluation",
            "n": 3,
            "set_name": "evaluation",
            "tiny": True,
            "version": 1,
            "round_id": round_id,
        },
    ).json()["run_id"]
    client.post(f"/api/rounds/{round_id}/halt", json={"reason": "It broke"})
    assert a_round(client, round_id)["stop_reason"] == "It broke"
    assert run(client, evaluation)["stop_reason"] == "It broke"


def test_quiet_is_measured_in_minutes():
    assert work.ago(5) < db.now()
