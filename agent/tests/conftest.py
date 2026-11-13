from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agent import checkpoints, client, graph, model
from agent.tests.serving import serving
from agent.tests.stubs import Backend, StubChecker
from backend.api import app
from backend.tests import judging, signing
from context.server import build_server


@pytest.fixture(autouse=True)
def checker(monkeypatch) -> StubChecker:
    """The security check's model, a stub that passes every claim unless told."""
    stub = StubChecker()
    monkeypatch.setattr(model, "check_model", lambda: stub)
    return stub


@pytest.fixture(scope="session")
def context_layer() -> Iterator[str]:
    """The real context layer, served once for all the agent's tests."""
    with serving(build_server().streamable_http_app()) as url:
        yield f"{url}/mcp"


@pytest.fixture
def requests(tmp_path, monkeypatch, context_layer) -> list[str]:
    """Point the agent at the backend with a fresh database and at the context
    layer; collect its requests to the backend."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("UNDERCOVER_CONTEXT", context_layer)
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
