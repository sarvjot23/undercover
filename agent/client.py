"""The agent's connection to the UnderCover backend, with the agent's API key."""

import os

import httpx

# The app's address: UNDERCOVER_API, which the deployment sets on Runtime.
BACKEND_URL = "http://127.0.0.1:8000"
# Longer than the backend waits for a database connection, so a busy swarm waits.
TIMEOUT = 150
KEY_HEADER = "X-API-Key"


def key_header() -> dict[str, str]:
    """The agent's key, read as each client is made: the command line loads it late."""
    return {KEY_HEADER: os.getenv("UNDERCOVER_API_KEY", "")}


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(
        base_url=os.getenv("UNDERCOVER_API") or BACKEND_URL,
        timeout=TIMEOUT,
        headers=key_header(),
    )


def reply(response: httpx.Response) -> str:
    """Return the backend's response as text for the model, refusals included."""
    if response.is_success:
        return response.text
    return f"Refused ({response.status_code}): {response.json()['detail']}"
