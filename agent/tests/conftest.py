import pytest
from fastapi.testclient import TestClient

from agent import checkpoints, client, graph
from agent.tests.stubs import Backend
from backend.api import app


@pytest.fixture
def requests(tmp_path, monkeypatch) -> list[str]:
    """Point the agent at the backend with a fresh database; collect its requests."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
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
