import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend import db, grading, judge
from backend.tests import deciding, judging
from backend.tests.signing import as_handler

HANDLER = {
    "decision": "approve",
    "reason": "The delay was over six hours and the receipts cover the costs.",
    "reference": "3. Trip Delay",
}
AGENT = {
    "decision": "approve",
    "reasons": "Covered under trip delay; the receipts support the costs.",
    "policy_section": "3. Trip Delay",
}
RUN = {"n": 25, "tiny": False, "version": None, "round_id": None}


def evaluate(client, set_name="evaluation", tiny=True):
    body = {**RUN, "kind": "evaluation", "set_name": set_name, "tiny": tiny}
    return client.post("/api/runs", json=body).json()


def decide(client, claim_id, decision="refer", payout=0.0):
    deciding.decide(
        client,
        claim_id,
        decision,
        payout,
        thread_id=f"{claim_id}-t",
        reasons="Needs a handler. The manual says so.",
        policy_section="Claims manual 2.",
    )


def test_the_letter_is_the_most_likely_grade_not_the_score_rounded(monkeypatch):
    # C is the most likely grade, though the score, 1.66, rounds to a B.
    probabilities = {"0": 0.14, "1": 0.36, "2": 0.2, "3": 0.3}
    judging.install(monkeypatch, lambda state: judging.response(1.66, probabilities))
    found = judge.grade(HANDLER, AGENT)
    assert found["grade"] == 1.66
    assert found["letter"] == "C"
    assert (found["same_grounds"], found["same_section"]) == (0.9, 0.8)
    assert found["cost"] == 0.0001


def test_the_judge_sees_the_handlers_reason_beside_the_agents(monkeypatch):
    asked = judging.install(monkeypatch)
    judge.grade(HANDLER, AGENT)
    assert asked == [
        {
            "handler": HANDLER,
            "agent": {
                "decision": "approve",
                "rationale": AGENT["reasons"],
                "section": "3. Trip Delay",
            },
        }
    ]


def test_the_judges_address_is_read_once_and_passed_on_each_call(monkeypatch):
    calls = []

    class Decisions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return judging.response()

    class Client:
        def __init__(self, api_key):
            self.alpha = SimpleNamespace(decisions=Decisions())

    monkeypatch.setattr(judge, "OpenRouter", Client)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("JUDGE_URL", "http://judge.test")
    judge.server_url.cache_clear()
    judge.ask({"handler": {}, "agent": {}})
    monkeypatch.setenv("JUDGE_URL", "http://elsewhere.test")
    judge.ask({"handler": {}, "agent": {}})
    judge.server_url.cache_clear()
    assert [call["server_url"] for call in calls] == ["http://judge.test"] * 2
    assert calls[0]["model"] == "typesafe/jev-1.13"
    assert calls[0]["timeout_ms"] == 10_000
    assert calls[0]["retries"].strategy == "none"
    assert set(calls[0]["questions"]) == {"grade", "same_grounds", "same_section"}


def test_the_judges_address_defaults_to_openrouter(monkeypatch):
    monkeypatch.delenv("JUDGE_URL", raising=False)
    judge.server_url.cache_clear()
    assert judge.server_url() == "https://openrouter.ai"
    judge.server_url.cache_clear()


def test_an_undecided_claim_gets_an_f_without_a_call(client, monkeypatch):
    asked = judging.install(monkeypatch)
    run = evaluate(client)
    first = run["claims"][0]["claim_id"]
    decide(client, first)
    client.post(f"/api/runs/{run['run_id']}/finish")
    found = client.get(f"/api/evaluations/{run['run_id']}", headers=as_handler()).json()
    assert len(asked) == 1
    rows = {row["claim_id"]: row for row in found["claims"]}
    assert rows[first]["letter"] == "B"
    undecided = [row for row in found["claims"] if row["claim_id"] != first]
    assert {row["letter"] for row in undecided} == {"F"}
    assert {row["grade"] for row in undecided} == {0.0}
    assert found["scores"]["grade"] == pytest.approx(2.0 / 5)


def test_an_ungraded_claim_is_left_out_of_the_average(client, monkeypatch):
    def flaky(state):
        if "first" in state["agent"]["rationale"]:
            raise TimeoutError("The judge took too long")
        return judging.response(3.0, {"3": 1.0})

    judging.install(monkeypatch, flaky)
    run = evaluate(client)
    claims = [entry["claim_id"] for entry in run["claims"]]
    for number, claim_id in enumerate(claims):
        deciding.decide(
            client,
            claim_id,
            "refer",
            0,
            reasons="The first one." if number == 0 else "Needs a handler.",
            policy_section="Claims manual 2.",
        )
    client.post(f"/api/runs/{run['run_id']}/finish")
    found = client.get(f"/api/evaluations/{run['run_id']}", headers=as_handler()).json()
    rows = {row["claim_id"]: row for row in found["claims"]}
    assert rows[claims[0]]["graded"] is False
    assert rows[claims[0]]["grade"] is None
    assert rows[claims[1]]["letter"] == "A"
    assert found["scores"]["grade"] == 3.0


def test_nothing_graded_means_no_grade(client, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    asked = judging.install(monkeypatch)
    run = evaluate(client)
    for entry in run["claims"]:
        decide(client, entry["claim_id"])
    client.post(f"/api/runs/{run['run_id']}/finish")
    found = client.get(f"/api/evaluations/{run['run_id']}", headers=as_handler()).json()
    assert asked == []
    assert found["scores"]["grade"] is None
    assert {row["graded"] for row in found["claims"]} == {False}


def test_the_judges_cost_is_kept_apart_from_the_claim_agents(client, monkeypatch):
    judging.install(monkeypatch, lambda state: judging.response(cost=0.002))
    run = evaluate(client)
    for entry in run["claims"]:
        decide(client, entry["claim_id"])
        client.post(
            f"/api/claims/{entry['claim_id']}/usage",
            json={
                "run_id": run["run_id"],
                "model": "openai/gpt-6-luna",
                "input_tokens": 100,
                "output_tokens": 10,
                "cost": 0.001,
                "key": f"gen-{entry['claim_id']}",
            },
        )
    client.post(f"/api/runs/{run['run_id']}/finish")
    scores = client.get(
        f"/api/evaluations/{run['run_id']}", headers=as_handler()
    ).json()["scores"]
    assert scores["cost"] == pytest.approx(0.005)
    assert scores["judge_cost"] == pytest.approx(0.010)


def test_grading_25_claims_finishes_within_20_seconds(monkeypatch):
    def slow(state):
        time.sleep(2)
        return judging.response()

    judging.install(monkeypatch, slow)
    work = [
        {"claim_id": f"EV1-CLM-{n}", "handler": HANDLER, "agent": AGENT}
        for n in range(25)
    ]
    started = time.monotonic()
    graded = grading.grade_all(work)
    assert time.monotonic() - started < 20
    assert len(graded) == 25
    assert all(found is not None for found in graded.values())


def test_a_dispatch_is_not_graded(client, monkeypatch):
    asked = judging.install(monkeypatch)
    body = {**RUN, "kind": "dispatch", "set_name": None}
    run = client.post("/api/runs", json=body).json()
    client.post(f"/api/runs/{run['run_id']}/finish")
    assert asked == []


def test_the_handlers_reasons_are_seeded_for_the_judge(client):

    with db.engine().connect() as conn:
        rows = conn.execute(select(db.handler_decisions)).mappings().all()
    assert len(rows) == 50
    assert all(row["reason"] and row["reference"] for row in rows)
