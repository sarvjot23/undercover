"""The agent's connection to the UnderCover backend."""

import httpx

BACKEND_URL = "http://127.0.0.1:8000"


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


def reply(response: httpx.Response) -> str:
    """Return the backend's response as text for the model, refusals included."""
    if response.is_success:
        return response.text
    return f"Refused ({response.status_code}): {response.json()['detail']}"
