import pytest
from fastapi.testclient import TestClient

from agent import checkpoints, client, graph, model
from agent.tests.stubs import Backend, StubChecker
from backend.api import app
from backend.tests import judging, signing


@pytest.fixture(autouse=True)
def checker(monkeypatch) -> StubChecker:
    """The security check's model, a stub that passes every claim unless told."""
    stub = StubChecker()
    monkeypatch.setattr(model, "check_model", lambda: stub)
    return stub


@pytest.fixture
def requests(tmp_path, monkeypatch) -> list[str]:
    """Point the agent at the backend with a fresh database; collect its requests."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
    signing.install(monkeypatch)
    judging.install(monkeypatch)
    with TestClient(app):
        pass
    paths: list[str] = []

    def backend():
        api = Backend(app)
        api.event_hooks = {"request": [lambda request: paths.append(request.url.path)]}
        return api

    monkeypatch.setattr(client, "backend", backend)
    monkeypatch.setattr(graph, "RETRY_DELAY", 0.0)
    checkpoints.memory.cache_clear()
    return paths
