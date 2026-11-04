import runpy
import sys
import threading
import time

import dotenv
import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler

from agent import checkpoints, dispatcher, graph, tracing
from agent import claim as claim_agent
from agent.tests.stubs import BrokenModel, RateLimitedModel, call, script
from backend import runs
from backend.api import app

RECORD = {
    "kind": "dispatch",
    "n": 1,
    "set_name": None,
    "tiny": False,
    "model": "openai/gpt-6-luna",
    "reasoning": "low",
}


def api():
    return TestClient(app)


def refer(claim_id):
    return call(
        "record_decision",
        claim_id=claim_id,
        decision="refer",
        payout=0,
        reasons="Needs a handler. The manual says so.",
        policy_section="Claims manual 2.",
    )


def approve(claim_id, payout):
    return call(
        "record_decision",
        claim_id=claim_id,
        decision="approve",
        payout=payout,
        reasons="The wording settles it. The documents support it.",
        policy_section="3. Trip Delay",
    )


def claim(claim_id):
    return api().get(f"/api/claims/{claim_id}").json()


def steps(claim_id):
    return api().get(f"/api/claims/{claim_id}/steps").json()


@pytest.fixture
def only(monkeypatch):
    """Keep a dispatch to these claims of the queue, in the queue's order."""

    def keep(*claim_ids):
        original = runs.dispatch_claims
        monkeypatch.setattr(
            runs,
            "dispatch_claims",
            lambda conn: [c for c in original(conn) if c in claim_ids],
        )

    return keep


@pytest.fixture
def models(monkeypatch):
    """Give each claim the next of its stub models each time the dispatcher works it."""
    monkeypatch.setattr(dispatcher, "FIRST_WAIT", 0.0)
    given = {}
    original = claim_agent.work

    def work(claim_id, in_run, llm=None):
        return original(claim_id, in_run, next(given[claim_id]))

    monkeypatch.setattr(claim_agent, "work", work)

    def give(claim_id, *stubs):
        given[claim_id] = iter(stubs)

    return give


def new_run() -> tracing.Run:
    created = api().post("/api/runs", json=RECORD).json()
    return {"run_id": created["run_id"], "kind": "dispatch"}


def test_never_more_than_n_claims_are_worked_at_once(requests, monkeypatch):
    claim_ids = [f"CLM-10{number:02d}" for number in range(1, 11)]
    inside = []
    most = []
    lock = threading.Lock()

    def work(claim_id, in_run):
        with lock:
            inside.append(claim_id)
            most.append(len(inside))
        time.sleep(0.05)
        with lock:
            inside.remove(claim_id)
        return f"{claim_id}: done"

    monkeypatch.setattr(claim_agent, "work", work)
    monkeypatch.setattr(graph, "standing", lambda claim_id: {"status": "decided"})
    monkeypatch.setattr(dispatcher, "list_claims", lambda state: {"claims": claim_ids})
    results = dispatcher.dispatch(new_run(), 3)
    assert sorted(results) == [f"{claim_id}: done" for claim_id in claim_ids]
    assert max(most) == 3


def test_a_dispatch_works_its_claims_and_finishes(requests, only, models):
    only("CLM-1001", "CLM-1002")
    models("CLM-1001", script(approve("CLM-1001", 420.0)))
    models("CLM-1002", script(refer("CLM-1002")))
    run = new_run()
    results = dispatcher.dispatch(run, 2)
    assert sorted(results) == ["CLM-1001: approve $420.00", "CLM-1002: refer $0.00"]
    ended = api().get(f"/api/runs/{run['run_id']}").json()
    assert ended["status"] == "finished"
    assert ended["summary"]["approved"] == 1
    assert claim("CLM-1001")["payment"]["amount"] == 420.0


def test_a_rate_limit_carries_on_as_the_same_attempt(requests, only, models):
    only("CLM-1001")
    limited = RateLimitedModel(
        limited=[2],
        messages=iter([call("get_claim", claim_id="CLM-1001"), refer("CLM-1001")]),
    )
    models("CLM-1001", limited, limited)
    dispatcher.dispatch(new_run(), 1)
    found = claim("CLM-1001")
    assert found["status"] == "decided"
    assert found["attempts"] == 0
    keys = [step["key"] for step in steps("CLM-1001")]
    assert len(keys) == len(set(keys))
    assert {key.split(":")[0] for key in keys} == {found["thread_id"]}
    assert [step["kind"] for step in steps("CLM-1001")].count("tool_call") == 2


def test_a_claim_still_rate_limited_stays_in_progress_for_the_next(
    requests, only, models
):
    only("CLM-1001", "CLM-1002")
    limited = RateLimitedModel(limited=[1, 2, 3, 4], messages=iter([]))
    models("CLM-1001", *[limited] * dispatcher.ATTEMPTS)
    models("CLM-1002", script(refer("CLM-1002")))
    run = new_run()
    results = dispatcher.dispatch(run, 1)
    assert "the next dispatch carries this claim on" in results[0]
    held = claim("CLM-1001")
    assert held["status"] == "in_progress"
    assert held["attempts"] == 0
    assert claim("CLM-1002")["status"] == "decided"
    assert api().get(f"/api/runs/{run['run_id']}").json()["status"] == "finished"

    models("CLM-1001", script(refer("CLM-1001")))
    dispatcher.dispatch(new_run(), 1)
    assert claim("CLM-1001")["status"] == "decided"
    assert claim("CLM-1001")["thread_id"] == held["thread_id"]
    assert claim("CLM-1001")["attempts"] == 0


def test_a_failed_claim_is_tried_again_in_the_same_dispatch(requests, only, models):
    only("CLM-1001")
    models("CLM-1001", BrokenModel(messages=iter([])), script(refer("CLM-1001")))
    dispatcher.dispatch(new_run(), 1)
    assert claim("CLM-1001")["status"] == "decided"
    assert claim("CLM-1001")["attempts"] == 1


def test_a_claim_that_fails_twice_is_left_for_a_handler(requests, only, models):
    only("CLM-1001")
    broken = BrokenModel(messages=iter([]))
    models("CLM-1001", broken, broken)
    run = new_run()
    dispatcher.dispatch(run, 1)
    assert claim("CLM-1001")["status"] == "needs_handler"
    summary = api().get(f"/api/runs/{run['run_id']}").json()["summary"]
    assert summary["left_for_handler"] == ["CLM-1001"]


def test_a_claim_being_resumed_after_a_sign_off_is_skipped(requests, only, models):
    claim_agent.run("CLM-1008", "CLM-1008-first", script(approve("CLM-1008", 2240.0)))
    api().post("/api/claims/CLM-1008/sign-off", json={"handler_id": "HND-01"})
    api().post("/api/claims/CLM-1008/lease", json={"worker": "the-service"})
    only("CLM-1008")
    models("CLM-1008", script())
    results = dispatcher.dispatch(new_run(), 1)
    assert results == ["CLM-1008: not picked up, another worker is on it"]
    assert claim("CLM-1008")["payment"] is None


def test_a_broken_dispatcher_stops_its_run(requests, monkeypatch):
    def broken(state):
        raise RuntimeError("backend away")

    monkeypatch.setattr(dispatcher, "list_claims", broken)
    run = new_run()
    with pytest.raises(RuntimeError):
        dispatcher.dispatch(run, 1)
    assert api().get(f"/api/runs/{run['run_id']}").json()["status"] == "stopped"


def test_each_claim_in_a_dispatch_is_traced_as_a_session_tagged_with_its_run(
    requests, monkeypatch, only, models
):
    seen = []

    class Spy(BaseCallbackHandler):
        def on_chain_start(self, serialized, inputs, *, parent_run_id=None, **kwargs):
            seen.append((parent_run_id, kwargs.get("tags"), kwargs.get("metadata")))

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr(tracing, "CallbackHandler", Spy)
    monkeypatch.setattr(tracing, "flush", lambda: None)
    only("CLM-1001")
    models("CLM-1001", script(refer("CLM-1001")))
    run = new_run()
    dispatcher.dispatch(run, 1)
    parent, _, metadata = seen[0]
    assert parent is None
    assert metadata["langfuse_tags"] == [f"dispatch-{run['run_id']}"]


def test_each_graph_run_gets_its_own_saver_on_one_pool(monkeypatch):
    opened = []

    class Pool:
        def __init__(self, url, **settings):
            opened.append(settings["max_size"])

        def connection(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql):
            return None

        def close(self):
            return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/app")
    monkeypatch.setattr(checkpoints, "ConnectionPool", Pool)
    monkeypatch.setattr(checkpoints.PostgresSaver, "setup", lambda self: None)
    checkpoints.pool.cache_clear()
    try:
        first, second = checkpoints.saver(), checkpoints.saver()
        assert first is not second
        assert first.conn is second.conn  # type: ignore[attr-defined]
        assert opened == [4]
    finally:
        checkpoints.pool.cache_clear()


def test_one_claim_still_runs_from_the_command_line(monkeypatch, capsys):
    worked = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda override: None)
    monkeypatch.setattr(
        claim_agent, "work", lambda claim_id, run: worked.append(run) or "done"
    )
    monkeypatch.setattr(sys, "argv", ["agent", "CLM-1001"])
    runpy.run_module("agent", run_name="__main__")
    assert worked == [None]
    assert capsys.readouterr().out == "done\n"
