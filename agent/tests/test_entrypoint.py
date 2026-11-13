import importlib
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent import checkpoints, claim, dispatcher, entrypoint, lease, ready
from agent.tests import stubs
from agent.tests.invoking import invoke, ping
from agent.tests.stubs import call, script
from backend import db as backend_db
from backend import rounds as round_records
from backend import runs
from backend.api import app as backend_app
from backend.tests.signing import as_agent, as_handler

REAL_SPAWN = entrypoint.spawn


def backend():
    return TestClient(backend_app, headers=as_agent())


def hold(claim_id="CLM-1001"):
    return claim.run(
        claim_id,
        f"{claim_id}-first",
        script(*stubs.decide("approve", 1200.0, claim_id)),
    )


def sign_off(claim_id="CLM-1001"):
    backend().post(f"/api/claims/{claim_id}/sign-off", headers=as_handler())


RECORD = {
    "kind": "dispatch",
    "n": 3,
    "set_name": None,
    "tiny": False,
    "version": None,
    "round_id": None,
}


def create_run(**record):
    """A dispatch or an evaluation, created as the app creates it."""
    return backend().post("/api/runs", json={**RECORD, **record}).json()["run_id"]


def run_status(run_id):
    return backend().get(f"/api/runs/{run_id}").json()


def open_round():
    """A round the app has opened, working."""
    with backend_db.engine().begin() as conn:
        return round_records.create(conn, "HND-01")["round_id"]


@pytest.fixture
def held(monkeypatch):
    """Runs the dispatcher takes on without working them."""
    taken = []
    monkeypatch.setattr(dispatcher, "dispatch", lambda run, n: taken.append((run, n)))
    return taken


@pytest.fixture
def not_ready(monkeypatch):
    """The agent as it starts: not yet ready, with nothing left over to stop."""
    monkeypatch.setitem(ready.state, "ready", False)


@pytest.fixture
def on_runtime(monkeypatch):
    """On Runtime: the deployment names each credential's provider in Identity, and
    a stand-in for Identity gives each its value, counting the fetches."""
    fetched = []

    def requires_api_key(*, provider_name):
        def decorator(func):
            def wrapper():
                fetched.append(provider_name)
                return func(api_key=f"value-from-{provider_name}")

            return wrapper

        return decorator

    monkeypatch.setattr(ready, "requires_api_key", requires_api_key)
    monkeypatch.setenv("AGENTCORE_CREDENTIAL_UNDERCOVER_API_KEY_NAME", "key-provider")
    monkeypatch.setenv("AGENTCORE_CREDENTIAL_OPENROUTER_API_KEY_NAME", "model-provider")
    monkeypatch.delenv("UNDERCOVER_API_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return fetched


def test_the_health_check_answers_without_the_key():
    assert invoke({"operation": "health"}, key=None).json() == {"healthy": True}


def test_importing_the_agent_opens_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(checkpoints, "pool", opened.append)
    monkeypatch.setenv("DATABASE_URL", "postgresql://nowhere/db")
    monkeypatch.setitem(ready.state, "ready", False)
    importlib.reload(entrypoint)
    assert opened == []
    assert ready.state["ready"] is False
    monkeypatch.setattr(entrypoint, "spawn", lambda work: work())


def test_the_first_request_gets_ready_once(monkeypatch, not_ready):
    opened = []
    monkeypatch.setattr(checkpoints, "pool", opened.append)
    monkeypatch.setenv("DATABASE_URL", "postgresql://somewhere/db")
    invoke({"operation": "health"}, key=None)
    invoke({"operation": "health"}, key=None)
    assert opened == ["postgresql://somewhere/db"]


def test_getting_ready_fails_without_the_key_and_tries_again(monkeypatch, not_ready):
    monkeypatch.delenv("UNDERCOVER_API_KEY")
    failed = invoke({"operation": "health"}, key=None)
    assert failed.status_code == 500
    assert "UNDERCOVER_API_KEY is missing" in failed.json()["error"]
    monkeypatch.setenv("UNDERCOVER_API_KEY", "a-key")
    assert invoke({"operation": "health"}, key=None).json() == {"healthy": True}


def test_on_runtime_the_first_request_fetches_each_credential_once(
    monkeypatch, not_ready, on_runtime
):
    invoke({"operation": "health"}, key=None)
    invoke({"operation": "health"}, key=None)
    assert sorted(on_runtime) == ["key-provider", "model-provider"]
    assert os.environ["UNDERCOVER_API_KEY"] == "value-from-key-provider"
    assert os.environ["OPENROUTER_API_KEY"] == "value-from-model-provider"


def test_off_runtime_a_request_without_the_key_is_refused(held):
    for key in (None, "wrong"):
        refused = invoke({"operation": "work_run", "run_id": 1}, key=key)
        assert refused.status_code == 401
        assert refused.json() == {"error": "The agent's key is missing or wrong"}
    assert held == []


def test_on_runtime_a_request_without_the_key_is_let_through(not_ready, on_runtime):
    answer = invoke({"operation": "stop_round", "round_id": 1}, key=None)
    assert answer.json() == {"accepted": True}


@pytest.mark.parametrize(
    ("payload", "problem"),
    [
        ({"operation": "work_run"}, "work_run.run_id: Field required"),
        ({"operation": "work_run", "run_id": "one"}, "work_run.run_id: Input should"),
        ({"operation": "work_run", "run_id": 1, "n": 3}, "work_run.n: Extra inputs"),
        ({"operation": "resume_claim", "claim": "CLM-1001"}, "claim_id: Field req"),
        ({"operation": "dance"}, "does not match any of the expected tags"),
        ({"run_id": 3}, "Unable to extract tag using discriminator 'operation'"),
    ],
)
def test_a_payload_that_is_wrong_gets_a_400_saying_what(held, payload, problem):
    answer = invoke(payload)
    assert answer.status_code == 400
    assert problem in answer.json()["error"]
    assert held == []


def wait_for(done):
    for _ in range(100):
        if done():
            return
        time.sleep(0.05)
    raise AssertionError("never happened")


def test_resuming_a_signed_off_claim_pays_it(requests, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    answer = invoke({"operation": "resume_claim", "claim_id": "CLM-1001"})
    assert answer.json() == {"accepted": True}
    found = backend().get("/api/claims/CLM-1001").json()
    assert found["status"] == "decided"
    assert found["payment"]["signed_off_by"] == "HND-01"
    assert not claim.paused("CLM-1001")


def test_resuming_again_is_refused_and_pays_once(requests, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    invoke({"operation": "resume_claim", "claim_id": "CLM-1001"})
    paid = backend().get("/api/claims/CLM-1001").json()["payment"]
    again = invoke({"operation": "resume_claim", "claim_id": "CLM-1001"})
    assert again.json() == {"refused": "Claim CLM-1001 isn't paused with an answer"}
    assert backend().get("/api/claims/CLM-1001").json()["payment"] == paid


def test_a_claim_held_by_another_worker_is_left_alone(requests, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    backend().post("/api/claims/CLM-1001/lease", json={"worker": "other"})
    invoke({"operation": "resume_claim", "claim_id": "CLM-1001"})
    found = backend().get("/api/claims/CLM-1001/steps").json()
    assert "answer" not in {step["kind"] for step in found}


def test_resume_refuses_a_claim_that_isnt_paused(requests):
    answer = invoke({"operation": "resume_claim", "claim_id": "CLM-1001"})
    assert answer.json() == {"refused": "Claim CLM-1001 isn't paused with an answer"}


def test_the_agent_starts_one_claim(monkeypatch):
    started = []
    monkeypatch.setattr(claim, "run", lambda *args: started.append(args))
    payload = {"operation": "work_claim", "claim_id": "CLM-1001", "thread_id": "t-1"}
    assert invoke(payload).json() == {"accepted": True}
    assert started == [("CLM-1001", "t-1")]


def test_a_stop_of_a_round_is_noted():
    answer = invoke({"operation": "stop_round", "round_id": 3})
    assert answer.json() == {"accepted": True}


def test_a_run_is_worked_on_its_version_with_its_n(requests, held):
    run_id = create_run(n=5)
    answer = invoke({"operation": "work_run", "run_id": run_id})
    assert answer.json() == {"accepted": True}
    [(run, n)] = held
    assert (run["run_id"], run["kind"], run["version"], n) == (run_id, "dispatch", 1, 5)


def test_a_run_that_isnt_running_is_refused(requests, held):
    run_id = create_run()
    backend().post(f"/api/runs/{run_id}/stop", json={"reason": "Stopped by a test"})
    answer = invoke({"operation": "work_run", "run_id": run_id})
    assert answer.json() == {"refused": f"Run {run_id} is stopped"}
    assert held == []


def test_a_dispatch_is_worked_to_the_end(requests, monkeypatch):
    original = runs.dispatch_claims
    monkeypatch.setattr(
        runs,
        "dispatch_claims",
        lambda conn: [c for c in original(conn) if c == "CLM-1002"],
    )
    monkeypatch.setattr(
        claim,
        "model",
        lambda name, reasoning: script(
            call(
                "record_decision",
                decision="refer",
                payout=0,
                reasons="Needs a handler. The manual says so.",
                policy_section="Claims manual 2.",
            )
        ),
    )
    monkeypatch.setattr(dispatcher, "FIRST_WAIT", 0.0)
    run_id = create_run(n=2)
    invoke({"operation": "work_run", "run_id": run_id})
    run = run_status(run_id)
    assert run["status"] == "finished"
    assert [entry["claim_id"] for entry in run["claims"]] == ["CLM-1002"]
    assert backend().get("/api/claims/CLM-1002").json()["status"] == "decided"


class BrokenDispatcher:
    """A dispatcher's graph that breaks."""

    def invoke(self, state, config):
        raise RuntimeError("broken")


def test_a_failed_run_stops_only_itself(requests, monkeypatch):
    monkeypatch.setattr(dispatcher, "build", BrokenDispatcher)
    round_id = open_round()
    run_id = create_run()
    invoke({"operation": "work_run", "run_id": run_id})
    stopped = run_status(run_id)
    assert stopped["status"] == "stopped"
    assert stopped["stop_reason"] == "The agent's work on it failed"
    assert backend().get(f"/api/rounds/{round_id}").json()["status"] == "working"


def test_the_agent_tells_the_app_every_minute_while_it_works(requests, monkeypatch):
    monkeypatch.setattr(lease, "REPORT_SECONDS", 0.01)
    release = threading.Event()
    monkeypatch.setattr(dispatcher, "dispatch", lambda run, n: release.wait(10))
    monkeypatch.setattr(entrypoint, "spawn", REAL_SPAWN)
    run_id = create_run()
    invoke({"operation": "work_run", "run_id": run_id})
    path = f"/api/runs/{run_id}/heard"
    wait_for(lambda: requests.count(path) >= 2)
    release.set()


def test_the_ping_is_busy_while_work_goes_on_and_healthy_after(requests, monkeypatch):
    monkeypatch.setattr(entrypoint, "spawn", REAL_SPAWN)
    release = threading.Event()
    monkeypatch.setattr(dispatcher, "dispatch", lambda run, n: release.wait(10))
    assert ping() == "Healthy"
    invoke({"operation": "work_run", "run_id": create_run()})
    assert ping() == "HealthyBusy"
    release.set()
    wait_for(lambda: ping() == "Healthy")


def test_the_ping_is_healthy_once_work_has_failed(requests, monkeypatch):
    monkeypatch.setattr(entrypoint, "spawn", REAL_SPAWN)
    release = threading.Event()

    def broken(run, n):
        release.wait(10)
        raise RuntimeError("broken")

    monkeypatch.setattr(dispatcher, "dispatch", broken)
    invoke({"operation": "work_run", "run_id": create_run()})
    assert ping() == "HealthyBusy"
    release.set()
    wait_for(lambda: ping() == "Healthy")


def test_a_round_that_isnt_open_is_refused(requests):
    round_id = open_round()
    backend().post(f"/api/rounds/{round_id}/halt", json={"reason": "A test"})
    answer = invoke({"operation": "work_round", "round_id": round_id})
    assert answer.json() == {"refused": f"Round {round_id} is stopped"}


def test_a_failed_round_stops_itself_and_its_running_evaluation(requests, monkeypatch):
    round_id = open_round()
    evaluation = create_run(
        kind="evaluation", set_name="evaluation", tiny=True, round_id=round_id
    )

    def broken(round_id):
        raise RuntimeError("broken")

    monkeypatch.setattr(entrypoint.rounds, "work", broken)
    invoke({"operation": "work_round", "round_id": round_id})
    found = backend().get(f"/api/rounds/{round_id}").json()
    assert (found["status"], found["stop_reason"]) == (
        "stopped",
        "The agent's work on it failed",
    )
    assert run_status(evaluation)["status"] == "stopped"


def test_a_resume_runs_beside_a_dispatch(requests, monkeypatch, held):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    create_run()
    answer = invoke({"operation": "resume_claim", "claim_id": "CLM-1001"})
    assert answer.json() == {"accepted": True}
    assert backend().get("/api/claims/CLM-1001").json()["status"] == "decided"
    assert not claim.paused("CLM-1001")
