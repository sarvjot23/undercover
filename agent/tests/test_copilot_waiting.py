"""Waiting for the agent's work in code, and the success criteria worked out from our
records, with a stub model, a fake clock and the agent's part played through the app."""

import json

import pytest
from langchain_core.messages import AIMessage

from agent import copilot_graph, copilot_waiting
from agent.tests import copiloting
from agent.tests.stubs import call, script
from backend.tests import deciding, signing


@pytest.fixture
def copilot(requests, monkeypatch):
    found = copiloting.Copilot()
    found.install(monkeypatch)
    monkeypatch.setenv("UNDERCOVER_API_KEY", signing.AGENT_KEY)
    return found


class Clock:
    """A clock that moves on by a step each time the Copilot pauses, and plays the
    agent's part on the first pause."""

    def __init__(self, step=5.0, agent=None):
        self.now = 0.0
        self.step = step
        self.agent = agent
        self.pauses = 0

    def __call__(self):
        return self.now

    def pause(self, seconds):
        self.pauses += 1
        self.now += self.step
        if self.agent and self.pauses == 1:
            self.agent()


@pytest.fixture
def clock(monkeypatch):
    found = Clock()
    monkeypatch.setattr(copilot_waiting, "clock", found)
    monkeypatch.setattr(copilot_waiting, "pause", found.pause)
    return found


def tool_answer(context, name):
    """What a tool answered on the turn, from its card."""
    turn = copiloting.conversation(context)["turns"][-1]
    return next(s for s in turn["steps"] if s["tool"] == name)


def finish_dispatch(run_id=1):
    """The agent works the dispatch: CLM-1003 held for sign-off, CLM-1002 referred."""
    with copiloting.as_agent() as agent:
        deciding.decide(agent, "CLM-1003", "approve", 3750.0)
        deciding.decide(agent, "CLM-1002", "refer", 0.0)
        agent.post(f"/api/runs/{run_id}/finish")


def test_a_dispatch_is_waited_on_in_code_then_what_needs_the_handler(copilot, clock):
    clock.agent = finish_dispatch
    context = copiloting.begin("Work the queue with 10 agents")
    llm = script(
        call("start_dispatch", agents=10),
        call("wait_for_work", run_id=1),
        AIMessage("CLM-1003 needs your sign-off."),
    )
    copilot_graph.turn(context, "Work the queue with 10 agents", llm)
    started = json.loads(tool_answer(context, "start_dispatch")["answer"])
    assert started == {"started": True, "run_id": 1}
    assert copilot.agent_work == [{"operation": "work_run", "run_id": 1}]
    waited = tool_answer(context, "wait_for_work")
    found = json.loads(waited["answer"])
    assert found["status"] == "finished"
    assert found["needs_you"]["held_for_sign_off"] == [
        {"claim_id": "CLM-1003", "customer": "Aiko Tanaka", "payout": 3750.0}
    ]
    assert found["needs_you"]["referred"] == ["CLM-1002"]
    turn = copiloting.conversation(context)["turns"][-1]
    assert turn["model_calls"] == 3  # waiting called the model no more


def test_a_dispatch_without_a_number_uses_the_settings(copilot, clock):
    context = copiloting.begin("Work the queue")
    llm = script(call("start_dispatch"), AIMessage("Started."))
    copilot_graph.turn(context, "Work the queue", llm)
    with copiloting.as_agent() as agent:
        assert agent.get("/api/runs/1").json()["n"] == 25


def test_a_start_the_app_refuses_is_passed_on(copilot, clock):
    context = copiloting.begin("Work the queue")
    llm = script(
        call("start_dispatch", agents=3),
        call("start_dispatch", agents=3),
        AIMessage("A dispatch is already running."),
    )
    copilot_graph.turn(context, "Work the queue", llm)
    turn = copiloting.conversation(context)["turns"][-1]
    second = turn["steps"][1]
    assert second["state"] == "refused"
    assert second["reason"] == "Refused (409): Dispatch 1 is running"


def test_after_15_minutes_the_wait_ends_saying_where_to_follow_it(copilot, clock):
    clock.step = 60.0
    context = copiloting.begin("Work the queue")
    llm = script(
        call("start_dispatch", agents=3),
        call("wait_for_work", run_id=1),
        AIMessage("It's still going."),
    )
    copilot_graph.turn(context, "Work the queue", llm)
    waited = tool_answer(context, "wait_for_work")["answer"]
    assert waited == (
        "Dispatch 1 is still going after 15 minutes. Follow it on the queue page."
    )
    assert clock.pauses == 15


def criteria_answer(context):
    return json.loads(tool_answer(context, "check_success_criteria")["answer"])


def check(context):
    llm = script(call("check_success_criteria"), AIMessage("Here's where we stand."))
    copilot_graph.turn(context, "Are we meeting the success criteria?", llm)
    return criteria_answer(context)


def finish_evaluation(decision="approve"):
    """The agent works the held-out evaluation, deciding every copy the same way."""

    def work():
        with copiloting.as_agent() as agent:
            run = agent.get("/api/runs/1").json()
            for entry in run["claims"]:
                payout = 100.0 if decision == "approve" else 0.0
                deciding.decide(agent, entry["claim_id"], decision, payout)
                if decision == "approve":
                    agent.post(
                        f"/api/claims/{entry['claim_id']}/payment",
                        json={"amount": payout},
                    )
            agent.post("/api/runs/1/finish")

    return work


def test_the_criteria_from_the_evaluation_settings_and_the_count(copilot, clock):
    clock.agent = finish_evaluation()
    context = copiloting.begin("Are we meeting the success criteria?")
    found = check(context)
    with copiloting.as_agent() as agent:
        run = agent.get("/api/runs/1").json()
    assert (run["kind"], run["set_name"], run["tiny"], run["n"]) == (
        "evaluation",
        "held_out",
        False,
        25,
    )
    measures = (
        copiloting.TestClient(copiloting.app, headers=signing.as_handler())
        .get("/api/evaluations/1/measures")
        .json()["scores"]
    )
    straight, accuracy, over = found["criteria"]
    assert straight["figure"] == f"{measures['straight_through']:.0%}"
    assert straight["met"] is (measures["straight_through"] >= 0.7)
    assert accuracy["target"] == "at least 60%"
    assert accuracy["figure"] == f"{measures['accuracy']:.0%}"
    assert accuracy["met"] is (measures["accuracy"] >= 0.6)
    assert over["figure"] == "none paid over $800.00 yet, so none needed a sign-off"
    assert over["met"] is True
    assert "| Over the limit |" in criteria_answer(context)["table"]


def test_a_payout_over_the_limit_without_a_sign_off_isnt_met(copilot, clock):
    clock.agent = finish_evaluation("refer")
    with copiloting.as_agent() as agent:
        deciding.decide(agent, "CLM-1001", "approve", 420.0)
        agent.post("/api/claims/CLM-1001/payment", json={"amount": 420.0})
        agent.put(
            "/api/settings",
            headers=signing.as_handler(),
            json={
                **agent.get("/api/settings").json()["settings"],
                "approval_limit": 400.0,
            },
        )
    context = copiloting.begin("Are we meeting the success criteria?")
    found = check(context)
    over = found["criteria"][2]
    assert over["figure"] == "0 of 1 signed off"
    assert over["met"] is False
    assert found["all_met"] is False


def test_an_evaluation_that_stops_gives_no_figures_but_the_third(copilot, clock):
    def stop():
        with copiloting.as_agent() as agent:
            agent.post("/api/runs/1/stop", json={"reason": "The agent's work failed"})

    clock.agent = stop
    context = copiloting.begin("Are we meeting the success criteria?")
    found = check(context)
    straight, accuracy, over = found["criteria"]
    assert straight["figure"] is None
    assert straight["met"] is None
    assert accuracy["figure"] is None
    assert accuracy["met"] is None
    assert over["met"] is True
    assert found["all_met"] is None
    assert found["from"] == "Evaluation 1 stopped partway: The agent's work failed"


def test_an_evaluation_the_app_refuses_still_reports_the_third(copilot, clock):
    with copiloting.TestClient(copiloting.app, headers=signing.as_handler()) as api:
        api.post("/api/dispatches", json={"n": 3})
    context = copiloting.begin("Are we meeting the success criteria?")
    found = check(context)
    assert found["from"] == "The evaluation didn't start: Dispatch 1 is running"
    assert found["criteria"][2]["met"] is True
