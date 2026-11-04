"""The backend's line to the agent's service, which runs as a process of its own."""

import os
from typing import NamedTuple

import httpx

DEFAULT_URL = "http://127.0.0.1:8002"
TIMEOUT = 5


class Answer(NamedTuple):
    """The service's answer: its status, and why if it refused."""

    status: int
    detail: str


def ask(path: str, body: dict[str, object]) -> Answer | None:
    """Ask the agent's service to do some work; return its answer, or None if away."""
    url = os.getenv("UNDERCOVER_AGENT", DEFAULT_URL)
    try:
        response = httpx.post(f"{url}{path}", json=body, timeout=TIMEOUT)
    except httpx.HTTPError:
        return None
    detail = "" if response.is_success else response.json().get("detail", "")
    return Answer(response.status_code, str(detail))


def tell(path: str, body: dict[str, object]) -> bool:
    """Ask the agent's service to do some work, and say whether it took it on."""
    answer = ask(path, body)
    return answer is not None and httpx.codes.is_success(answer.status)


def resume(claim_id: str) -> None:
    """Tell the agent a claim is signed off. If it's away, it picks it up next time."""
    tell(f"/claims/{claim_id}/resume", {})
