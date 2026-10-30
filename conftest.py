import pytest


@pytest.fixture(autouse=True)
def no_outside_services(monkeypatch):
    """Keep the tests off Supabase, Langfuse and the real agent service."""
    for name in (
        "DATABASE_URL",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UNDERCOVER_AGENT", "http://127.0.0.1:1")
