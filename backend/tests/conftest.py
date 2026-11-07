from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.tests import judging, signing


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A client for the backend with a fresh database and the test signing key."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
    signing.install(monkeypatch)
    judging.install(monkeypatch)
    with TestClient(app, headers=signing.as_agent()) as test_client:
        yield test_client
