import httpx
from fastapi.testclient import TestClient

from agent import claim, client, queue, service
from agent.tests.stubs import call, script
from backend.api import app as backend_app


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
    backend().post(f"/api/claims/{claim_id}/sign-off", json={"handler_id": "HND-01"})


def test_health():
    assert agent_service().get("/health").json() == {"status": "ok"}


def test_every_operation_is_documented_with_no_optional_inputs():
    schema = service.app.openapi()
    for path in schema["paths"].values():
        for operation in path.values():
            assert operation["operationId"]
            assert "\n" not in operation["description"]
            assert all(param["required"] for param in operation.get("parameters", []))


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


def test_the_service_starts_claims_and_runs(monkeypatch):
    started = []
    monkeypatch.setattr(claim, "run", lambda *args: started.append(args))
    monkeypatch.setattr(queue, "run", lambda *args: started.append(args))
    body = {"thread_id": "CLM-1001-x"}
    agent_service().post("/claims/CLM-1001/run", json=body)
    agent_service().post("/runs/7")
    assert started == [("CLM-1001", "CLM-1001-x"), (7,)]


def test_signed_off_claims_are_picked_up_when_the_service_starts(requests, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    hold()
    sign_off()
    hold("CLM-1002")
    service.pick_up_signed_off()
    assert backend().get("/api/claims/CLM-1001").json()["status"] == "decided"
    assert backend().get("/api/claims/CLM-1002").json()["payment"] is None


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
    assert service.signed_off_claims() == []
    assert len(tries) == 2


def test_the_service_gives_up_if_the_backend_never_comes(monkeypatch):
    def down():
        raise httpx.ConnectError("not up")

    monkeypatch.setattr(client, "backend", down)
    monkeypatch.setattr(service, "BACKEND_WAIT_SECONDS", 0)
    monkeypatch.setattr(service, "BACKEND_WAIT_TRIES", 2)
    assert service.signed_off_claims() == []
