import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent import claim, dispatcher, improver, rounds, service, tracing
from agent.tests.stubs import StubModel, call
from backend import evaluations, spending
from backend.api import app
from backend.tests.signing import as_agent, as_handler

CHANGE = {
    "instructions": "Refer a claim when a required document is missing.",
    "model": "openai/gpt-6-luna",
    "reasoning_effort": "medium",
    "reason": "The misses had a document missing.",
}
RECIPE = {"recipe": "1. Call read_results.\n2. Propose one rule.", "reason": "Smaller."}
APPROVE = {"decision": "approve", "message": "", "handler_id": "HND-01"}
REJECTION = "Too broad: it would refer every claim."
COST = 0.001


class DecidingModel(StubModel):
    """A claim agent that refers whichever claim it's given, at $0.001 a reply."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if isinstance(last, HumanMessage):
            message = call(
                "record_decision",
                decision="refer",
                payout=0,
                reasons="Needs a handler. The manual says so.",
                policy_section="Claims manual 2.",
            )
        else:
            message = AIMessage(content="Referred.")
        message.id = f"gen-{uuid.uuid4().hex}"
        message.response_metadata = {
            "model_name": "openai/gpt-6-luna",
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "cost": 0.001,
            },
        }
        return ChatResult(generations=[ChatGeneration(message=message)])


class Improver(StubModel):
    """The improver's model: scripted replies, keeping what it was shown."""

    seen: list = []
    bound: list = []

    def bind_tools(self, tools, **kwargs):
        self.bound.append(kwargs)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, stop, run_manager, **kwargs)


def improver_script(*replies):
    return Improver(messages=iter(replies), seen=[], bound=[])


@pytest.fixture
def small(monkeypatch):
    """Evaluations of two claims from each set, worked by stub claim agents."""
    original = evaluations.source_claims
    monkeypatch.setattr(
        evaluations,
        "source_claims",
        lambda conn, set_name, tiny: original(conn, set_name, tiny)[:2],
    )
    monkeypatch.setattr(
        claim, "model", lambda name, reasoning: DecidingModel(messages=iter([]))
    )
    monkeypatch.setattr(dispatcher, "FIRST_WAIT", 0.0)
    yield
    if service.busy.locked():
        service.let_go()


def plays(monkeypatch, model):
    monkeypatch.setattr(improver, "model", lambda name, effort: model)
    return model


def agent_service():
    return TestClient(service.app)


def api():
    return TestClient(app, headers=as_agent())


def start_round():
    started = agent_service().post("/rounds", json={"handler_id": "HND-01"})
    assert started.status_code == 202
    return started.json()["round_id"]


def decide(round_id, decision=APPROVE):
    return agent_service().post(f"/rounds/{round_id}/decision", json=decision)


def found(round_id):
    return api().get(f"/api/rounds/{round_id}").json()


def current():
    return api().get("/api/configuration/current").json()["version"]


def test_a_round_from_start_to_finish(requests, small, monkeypatch):
    model = plays(
        monkeypatch,
        improver_script(
            call("read_results"),
            call("propose_change", **{**CHANGE, "reasoning_effort": "low"}),
            call("propose_change", **CHANGE),
            call("run_evaluation"),
            call("propose_recipe", **RECIPE),
            AIMessage(content="The round is done."),
        ),
    )
    round_id = start_round()

    waiting = found(round_id)
    assert (waiting["status"], waiting["stage"]) == ("waiting", "change_waiting")
    assert [run["set_name"] for run in waiting["evaluations"]] == [
        "evaluation",
        "held_out",
        "held_out",
    ]
    assert {run["status"] for run in waiting["evaluations"]} == {"finished"}
    assert waiting["proposal"]["reasoning"] == "low"
    assert "Call read_results" in str(model.seen[0][0].content)
    # The proposal changes nothing until a handler approves it.
    assert (
        len(api().get("/api/configuration/versions", headers=as_handler()).json()) == 1
    )

    rejection = {**APPROVE, "decision": "reject", "message": REJECTION}
    assert decide(round_id, rejection).status_code == 202
    assert any(REJECTION in str(message.content) for message in model.seen[-1])
    again = found(round_id)
    assert again["stage"] == "change_waiting"
    assert again["proposal"]["reasoning"] == "medium"
    assert again["version_tried"] is None

    decide(round_id)
    judged = found(round_id)
    assert judged["stage"] == "recipe_waiting"
    assert judged["version_tried"] == 2
    assert judged["verdict"] == "rolled_back"
    assert judged["why"] == "it missed the objectives on accuracy"
    assert len(judged["evaluations"]) == 6
    assert {run["version"] for run in judged["evaluations"][3:]} == {2}
    assert "Rolled back version 2" in str(model.seen[-1][-1].content)
    assert current() == 1

    decide(round_id)
    done = found(round_id)
    assert (done["status"], done["stage"]) == ("finished", "finished")
    assert [(e["decision"], e["proposal"]) for e in done["events"]] == [
        ("reject", "change"),
        ("approve", "change"),
        ("approve", "recipe"),
    ]
    assert done["events"][0]["message"] == REJECTION
    assert (
        api().get("/api/recipes", headers=as_handler()).json()[0]["recipe"]
        == RECIPE["recipe"]
    )
    assert done["spent"] > 0
    assert {kwargs["parallel_tool_calls"] for kwargs in model.bound} == {False}
    assert not service.busy.locked()


def test_a_proposal_outside_the_models_allowed_goes_back_without_a_pause(
    requests, small, monkeypatch
):
    model = plays(
        monkeypatch,
        improver_script(
            call("propose_change", **{**CHANGE, "model": "someone/else"}),
            AIMessage(content="Nothing allowed would help."),
        ),
    )
    round_id = start_round()
    done = found(round_id)
    assert done["status"] == "finished"
    assert done["events"] == []
    assert done["version_tried"] is None
    assert "isn't one of the models allowed" in str(model.seen[-1][-1].content)


def test_an_approval_is_refused_while_a_dispatch_runs(requests, small, monkeypatch):
    plays(monkeypatch, improver_script(call("propose_change", **CHANGE)))
    round_id = start_round()
    release = threading.Event()
    monkeypatch.setattr(dispatcher, "dispatch", lambda run, n: release.wait(10))
    running = threading.Thread(
        target=lambda: agent_service().post("/dispatches", json={"n": 3})
    )
    running.start()
    try:
        for _ in range(100):
            if service.doing["what"].startswith("Dispatch"):
                break
            time.sleep(0.05)
        refused = decide(round_id)
    finally:
        release.set()
        running.join()
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("Dispatch ")
    assert refused.json()["detail"].endswith(" is running")
    assert found(round_id)["events"] == []
    assert found(round_id)["stage"] == "change_waiting"


def test_an_evaluation_over_whats_left_is_refused_and_the_version_rolled_back(
    requests, small, monkeypatch
):
    settings = api().get("/api/settings").json()["settings"]
    api().put(
        "/api/settings",
        json={**settings, "round_spending_limit": 0.05},
        headers=as_handler(),
    )
    model = plays(
        monkeypatch,
        improver_script(
            call("propose_change", **CHANGE),
            call("run_evaluation"),
            AIMessage(content="Out of money."),
        ),
    )
    round_id = start_round()
    decide(round_id)
    done = found(round_id)
    assert done["verdict"] == "rolled_back"
    assert done["why"] == "the round couldn't afford to evaluate it"
    assert len(done["evaluations"]) == 3
    assert str(model.seen[-1][-1].content).startswith("Refused: the evaluation")


def test_an_evaluation_cut_short_by_the_limit_is_stopped(requests, small, monkeypatch):
    # Each evaluation is estimated at one claim, so it is allowed to start.
    monkeypatch.setattr(spending, "whole_set_claims", lambda conn: 1)
    settings = api().get("/api/settings").json()["settings"]
    api().put(
        "/api/settings",
        json={**settings, "round_spending_limit": 0.008},
        headers=as_handler(),
    )
    plays(
        monkeypatch,
        improver_script(
            call("propose_change", **CHANGE),
            call("run_evaluation"),
            AIMessage(content="Done."),
        ),
    )
    round_id = start_round()
    decide(round_id)
    done = found(round_id)
    tried = [run for run in done["evaluations"] if run["version"] == 2]
    assert [run["status"] for run in tried] == ["finished", "stopped"]
    assert done["verdict"] == "rolled_back"
    assert done["why"] == "its evaluations didn't all finish"
    assert current() == 1


def test_a_stopped_round_records_nothing_more(requests, small, monkeypatch):
    plays(monkeypatch, improver_script(call("propose_change", **CHANGE)))
    round_id = start_round()
    api().post(f"/api/rounds/{round_id}/stop", headers=as_handler())
    refused = decide(round_id)
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"Round {round_id} is stopped"
    assert found(round_id)["version_tried"] is None
    assert not service.busy.locked()


def test_a_stopped_round_makes_no_more_model_calls(requests, monkeypatch):
    round_id = api().post("/api/rounds/records", json={"handler_id": "HND-01"})
    round_id = round_id.json()["round_id"]
    api().post(f"/api/rounds/{round_id}/halt")
    guard = improver.RoundGuard(round_id)
    assert guard.before_model({}, None) == {"jump_to": "end"}


def test_a_round_waiting_survives_a_restart_and_one_working_is_stopped(
    requests, small, monkeypatch
):
    plays(
        monkeypatch,
        improver_script(
            call("propose_change", **CHANGE),
            call("propose_recipe", **RECIPE),
        ),
    )
    round_id = start_round()
    service.stop_leftovers()
    assert found(round_id)["status"] == "waiting"
    decide(round_id)
    assert found(round_id)["stage"] == "recipe_waiting"
    api().post(f"/api/rounds/{round_id}/stop", headers=as_handler())

    working = api().post("/api/rounds/records", json={"handler_id": "HND-01"}).json()
    service.stop_leftovers()
    assert found(working["round_id"])["status"] == "stopped"


def test_a_round_needs_nothing_first_once_the_current_version_has_its_runs(
    requests, small, monkeypatch
):
    plays(
        monkeypatch,
        improver_script(
            AIMessage(content="Nothing to change."),
            AIMessage(content="Still nothing."),
        ),
    )
    first = start_round()
    assert len(found(first)["evaluations"]) == 3
    second = start_round()
    assert found(second)["evaluations"] == []
    assert found(second)["status"] == "finished"


def test_the_improvers_calls_are_recorded_with_its_round(requests):
    round_id = api().post("/api/rounds/records", json={"handler_id": "HND-01"})
    round_id = round_id.json()["round_id"]
    guard = improver.RoundGuard(round_id)
    reply = AIMessage(
        content="",
        id="gen-improver-1",
        response_metadata={
            "model_name": "openai/gpt-6-luna",
            "token_usage": {
                "prompt_tokens": 900,
                "completion_tokens": 90,
                "cost": 0.02,
            },
        },
    )
    guard.record(reply)
    guard.record(reply)
    guard.record(AIMessage(content="no usage"))
    spent = api().get(f"/api/rounds/{round_id}/spending").json()["spent"]
    assert spent == pytest.approx(0.02)


def test_a_rounds_traces_share_a_session_and_its_evaluations_carry_its_tag():
    config = tracing.round_config("round-3-abc", 3)
    metadata = config.get("metadata", {})
    assert metadata["langfuse_session_id"] == "round-3-abc"
    assert "round-3" in metadata["langfuse_tags"]
    assert config.get("configurable", {})["thread_id"] == "round-3-abc"
    run: tracing.Run = {"run_id": 14, "kind": "evaluation", "version": 2, "round_id": 3}
    tags = tracing.config("EV14-CLM-1001-x", 10, run).get("metadata", {})
    assert tags["langfuse_tags"] == ["evaluation-14", "round-3"]


def test_the_improver_is_built_on_luna_at_medium(requests, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    round_id = api().post("/api/rounds/records", json={"handler_id": "HND-01"})
    agent = improver.build(round_id.json()["round_id"], rounds.evaluate_version)
    assert agent.name == "improver"
