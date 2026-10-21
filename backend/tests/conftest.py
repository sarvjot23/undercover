from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A client for the backend with a fresh database."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client
