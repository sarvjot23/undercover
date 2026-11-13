from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.tests import judging, signing

# Nothing listens here, so a request is refused at once.
CLOSED = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def no_agent(monkeypatch) -> None:
    """No test reaches AWS or a running agent: the laptop route goes to a closed
    port, and the Runtime route is off."""
    monkeypatch.setenv("UNDERCOVER_AGENT", CLOSED)
    monkeypatch.delenv("UNDERCOVER_AGENT_RUNTIME", raising=False)


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A client for the backend with a fresh database and the test signing key."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
    signing.install(monkeypatch)
    judging.install(monkeypatch)
    with TestClient(app, headers=signing.as_agent()) as test_client:
        yield test_client
