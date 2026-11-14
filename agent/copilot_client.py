"""The Copilot's connection to the app, with the sign-in of the handler it works for.

It never sends the agent's API key: the app treats a request with the key as the
agent's, which could record a decision or pay a claim.
"""

import os
from typing import Any

import httpx

from agent.client import BACKEND_URL

TIMEOUT = 60


class Refused(Exception):
    """The app refused a request, with its status and why."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Refused ({status}): {detail}")
        self.status = status
        self.detail = detail


def connect(token: str) -> httpx.Client:
    """A client for the app as the handler signed in, and nobody else."""
    return httpx.Client(
        base_url=os.getenv("UNDERCOVER_API") or BACKEND_URL,
        timeout=TIMEOUT,
        headers={"Authorization": f"Bearer {token}"},
    )


def detail_of(response: httpx.Response) -> str:
    """Why the app refused, as it says."""
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        return response.text
    return detail if isinstance(detail, str) else str(detail)


def call(token: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Call the app as the handler, and give its answer, or raise Refused."""
    with connect(token) as app:
        response = app.request(method, path, json=body)
    if not response.is_success:
        raise Refused(response.status_code, detail_of(response))
    return response.json()
