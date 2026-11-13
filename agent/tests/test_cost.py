from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import select

from agent import claim as claim_agent
from agent import graph, model, tracing
from agent.tests import stubs
from agent.tests.stubs import call, script
from backend import db
from backend.api import app
from backend.tests.signing import as_agent, as_handler

CLAIM = "CLM-1001"
RUN: tracing.Run = {"run_id": 12, "kind": "dispatch", "version": 1, "round_id": None}


def priced(message, number, cost=0.002):
    """A model reply carrying OpenRouter's usage, as the real model's replies do."""
    message.id = f"gen-{number}"
    message.response_metadata = {
        "model_name": "openai/gpt-6-luna",
        "token_usage": {"prompt_tokens": 1000, "completion_tokens": 50, "cost": cost},
    }
    return message


def refer():
    return call(
        "record_decision",
        decision="refer",
        payout=0,
        reasons="Needs a handler. The manual says so.",
        policy_section="Claims manual 2.",
    )


def approve(payout):
    return stubs.decide("approve", payout, CLAIM)


def rows(table):
    with db.engine().connect() as conn:
        return [dict(row) for row in conn.execute(select(table)).mappings()]


def test_a_version_chooses_the_model_and_its_effort(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    built = model.model("openai/gpt-6-luna", "low")
    assert built.model_name == "openai/gpt-6-luna"
    assert built.reasoning_effort == "low"
    assert model.model("openai/gpt-6-luna", "none").reasoning_effort == "none"
    assert model.model("openai/gpt-6-luna", "default").reasoning_effort is None


def test_model_name_chooses_another_model_with_no_effort(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    built = model.model("openai/gpt-6-luna", "low")
    assert built.model_name == "openrouter/free"
    assert built.reasoning_effort is None


def test_each_replys_tokens_and_cost_are_recorded_once(requests):
    claim_agent.run(
        CLAIM,
        "thread-1",
        script(
            priced(call("get_claim"), 1),
            priced(refer(), 2, cost=0.003),
        ),
    )
    recorded = rows(db.usage)
    assert [row["key"] for row in recorded] == ["gen-1", "gen-2"]
    assert recorded[0]["input_tokens"] == 1000
    assert recorded[0]["output_tokens"] == 50
    assert recorded[0]["model"] == "openai/gpt-6-luna"
    assert sum(row["cost"] for row in recorded) == 0.005
    assert {row["claim_id"] for row in recorded} == {CLAIM}


def test_a_reply_recorded_again_after_a_crash_counts_once(requests):
    reply = priced(AIMessage(content="Thinking."), 7)
    graph.record_usage(CLAIM, None, reply)
    graph.record_usage(CLAIM, None, reply)
    assert len(rows(db.usage)) == 1


def test_a_reply_without_usage_records_nothing(requests):
    claim_agent.run(CLAIM, "thread-1", script(refer()))
    assert rows(db.usage) == []


def test_usage_and_time_are_recorded_with_their_run(requests):
    claim_agent.run(CLAIM, "thread-1", script(priced(refer(), 3)), RUN)
    assert [row["run_id"] for row in rows(db.usage)] == [12]
    assert [row["run_id"] for row in rows(db.work_sessions)] == [12]


def test_usage_and_time_have_no_run_when_there_is_none(requests):
    claim_agent.run(CLAIM, "thread-1", script(priced(refer(), 4)))
    assert [row["run_id"] for row in rows(db.usage)] == [None]
    assert [row["run_id"] for row in rows(db.work_sessions)] == [None]


def test_the_wait_for_a_sign_off_is_not_counted(requests, monkeypatch):
    start = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
    times = iter(
        [
            start,
            start + timedelta(seconds=10),
            start + timedelta(days=2),
            start + timedelta(days=2, seconds=3),
        ]
    )
    monkeypatch.setattr(claim_agent, "clock", lambda: next(times))
    claim_agent.run(CLAIM, "thread-1", script(*approve(1200.0)), RUN)
    TestClient(app, headers=as_agent()).post(
        f"/api/claims/{CLAIM}/sign-off", headers=as_handler()
    )
    claim_agent.carry_on(CLAIM, script())
    sessions = rows(db.work_sessions)
    assert [row["seconds"] for row in sessions] == [10.0, 3.0]
    assert [row["run_id"] for row in sessions] == [12, None]
    assert (
        TestClient(app, headers=as_agent()).get(f"/api/claims/{CLAIM}").json()["status"]
        == "decided"
    )


def test_the_trace_is_tagged_with_its_run():
    config = tracing.config("CLM-1001-ab12cd34", 10, RUN)
    assert config.get("metadata") == {
        "langfuse_session_id": "CLM-1001-ab12cd34",
        "langfuse_tags": ["dispatch-12"],
    }
    assert config.get("configurable") == {
        "thread_id": "CLM-1001-ab12cd34",
        "run_id": 12,
    }


def test_a_trace_with_no_run_has_no_tag():
    config = tracing.config("CLM-1001-ab12cd34", 10, None)
    assert config.get("metadata") == {"langfuse_session_id": "CLM-1001-ab12cd34"}
