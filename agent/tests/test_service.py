import httpx
import pytest
from fastapi.testclient import TestClient

from agent import claim, client, dispatcher, service
from agent.tests.stubs import call, script
from backend import runs
from backend.api import app as backend_app
from backend.tests.signing import as_handler


def agent_service():
    return TestClient(service.app)


def backend():
    return TestClient(backend_app)


def hold(claim_id="CLM-1001"):
    return claim.run(
        claim_id,
        f"{claim_id}-first",
        script(
            call(
                "record_decision",
                claim_id=claim_id,
                decision="approve",
                payout=1200.0,
                reasons="The wording settles it. The documents support it.",
                policy_section="3. Trip Delay",
            )
        ),
    )


def sign_off(claim_id="CLM-1001"):
    backend().post(f"/api/claims/{claim_id}/sign-off", headers=as_handler())


@pytest.fixture
def held(monkeypatch):
    """Take on runs without working them, so the service stays busy."""
    taken = []
    monkeypatch.setattr(service, "work_run", lambda record, n: taken.append(record))
    yield taken
    if service.busy.locked():
        service.busy.release()


def test_health():
    assert agent_service().get("/health").json() == {"status": "ok"}


def test_every_operation_is_documented_with_no_optional_inputs():
    schema = service.app.openapi()
    for path in schema["paths"].values():
        for operation in path.values():
            assert operation["operationId"]
            assert "\n" not in operation["description"]
            assert all(param["required"] for param in operation.get("parameters", []))
    for model in schema["components"]["schemas"].values():
        if model["title"] in {"HTTPValidationError", "ValidationError"}:
            continue
        assert set(model["properties"]) == set(model.get("required", []))


def test_a_dispatch_is_taken_on_at_once_on_the_current_version(held, monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    started = agent_service().post("/dispatches", json={"n": 5})
    assert started.status_code == 202
    assert started.json() == {"accepted": True}
    assert held == [
        {
            "kind": "dispatch",
            "set_name": None,
            "tiny": False,
            "n": 5,
            "version": None,
            "round_id": None,
        }
    ]


def test_an_evaluation_is_taken_on_with_its_set(held, monkeypatch):
    body = {"set_name": "held_out", "tiny": True, "n": 5}
    assert agent_service().post("/evaluations", json=body).status_code == 202
    assert held[0]["set_name"] == "held_out"
    assert held[0]["tiny"] is True
    assert held[0]["version"] is None


def test_a_second_start_is_refused_while_a_run_is_going(held):
    agent_service().post("/dispatches", json={"n": 3})
    refused = agent_service().post(
        "/evaluations", json={**{"n": 3}, "set_name": "evaluation", "tiny": False}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "A dispatch or evaluation is already running"
    assert len(held) == 1


def test_a_dispatch_is_created_through_the_backend_and_worked(requests, monkeypatch):
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
                claim_id="CLM-1002",
                decision="refer",
                payout=0,
                reasons="Needs a handler. The manual says so.",
                policy_section="Claims manual 2.",
            )
        ),
    )
    monkeypatch.setattr(dispatcher, "FIRST_WAIT", 0.0)
    assert agent_service().post("/dispatches", json={"n": 2}).status_code == 202
    run = backend().get("/api/runs/current").json()
    assert run["status"] == "finished"
    assert run["n"] == 2
    assert [entry["claim_id"] for entry in run["claims"]] == ["CLM-1002"]
    assert backend().get("/api/claims/CLM-1002").json()["status"] == "decided"
    assert not service.busy.locked()


def test_the_service_is_freed_when_a_run_breaks(requests, monkeypatch):
    def broken(run, n):
        raise RuntimeError("broken")

    monkeypatch.setattr(dispatcher, "dispatch", broken)
    with pytest.raises(RuntimeError):
        service.work_run(
            {
                "kind": "dispatch",
                "n": 1,
                "set_name": None,
                "tiny": False,
                "version": None,
                "round_id": None,
            },
            1,
        )
    assert not service.busy.locked()


def test_resuming_a_signed_off_claim_pays_it(requests, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    assert agent_service().post("/claims/CLM-1001/resume").status_code == 200
    found = backend().get("/api/claims/CLM-1001").json()
    assert found["status"] == "decided"
    assert found["payment"]["signed_off_by"] == "HND-01"


def test_resuming_twice_pays_once(requests, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    agent_service().post("/claims/CLM-1001/resume")
    paid = backend().get("/api/claims/CLM-1001").json()["payment"]
    agent_service().post("/claims/CLM-1001/resume")
    assert backend().get("/api/claims/CLM-1001").json()["payment"] == paid


def test_a_claim_held_by_another_worker_is_left_alone(requests, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    backend().post("/api/claims/CLM-1001/lease", json={"worker": "other"})
    agent_service().post("/claims/CLM-1001/resume")
    assert backend().get("/api/claims/CLM-1001").json()["payment"] is None


def test_the_service_starts_one_claim(monkeypatch):
    started = []
    monkeypatch.setattr(claim, "run", lambda *args: started.append(args))
    agent_service().post("/claims/CLM-1001/run", json={"thread_id": "CLM-1001-x"})
    assert started == [("CLM-1001", "CLM-1001-x")]


def test_at_startup_signed_off_claims_are_paid_and_a_leftover_run_stopped(
    requests, monkeypatch
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    hold("CLM-1002")
    record = {
        "kind": "dispatch",
        "n": 3,
        "set_name": None,
        "tiny": False,
        "version": None,
        "round_id": None,
    }
    run_id = backend().post("/api/runs", json=record).json()["run_id"]
    service.pick_up_signed_off()
    assert backend().get("/api/claims/CLM-1001").json()["status"] == "decided"
    assert backend().get("/api/claims/CLM-1002").json()["payment"] is None
    assert backend().get(f"/api/runs/{run_id}").json()["status"] == "stopped"


def test_the_service_waits_for_the_backend(requests, monkeypatch):
    backend_factory = client.backend
    tries = []

    def flaky():
        tries.append(1)
        if len(tries) == 1:
            raise httpx.ConnectError("not up yet")
        return backend_factory()

    monkeypatch.setattr(client, "backend", flaky)
    monkeypatch.setattr(service, "BACKEND_WAIT_SECONDS", 0)
    assert len(service.backend_claims()) == 25
    assert len(tries) == 2


def test_the_service_gives_up_if_the_backend_never_comes(monkeypatch):
    def down():
        raise httpx.ConnectError("not up")

    monkeypatch.setattr(client, "backend", down)
    monkeypatch.setattr(service, "BACKEND_WAIT_SECONDS", 0)
    monkeypatch.setattr(service, "BACKEND_WAIT_TRIES", 2)
    assert service.backend_claims() == []
    service.pick_up_signed_off()
