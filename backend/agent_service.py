"""The backend's line to the agent's service, which runs as a process of its own."""

import os

import httpx

DEFAULT_URL = "http://127.0.0.1:8002"
TIMEOUT = 5


def ask(path: str, body: dict[str, object]) -> int | None:
    """Ask the agent's service to do some work; return its status, or None if away."""
    url = os.getenv("UNDERCOVER_AGENT", DEFAULT_URL)
    try:
        return httpx.post(f"{url}{path}", json=body, timeout=TIMEOUT).status_code
    except httpx.HTTPError:
        return None


def tell(path: str, body: dict[str, object]) -> bool:
    """Ask the agent's service to do some work, and say whether it took it on."""
    status = ask(path, body)
    return status is not None and httpx.codes.is_success(status)


def resume(claim_id: str) -> None:
    """Tell the agent a claim is signed off. If it's away, it picks it up next time."""
    tell(f"/claims/{claim_id}/resume", {})
