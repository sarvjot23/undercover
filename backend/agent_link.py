"""The backend's line to the agent's service, which runs as a process of its own."""

import os

import httpx

DEFAULT_URL = "http://127.0.0.1:8002"
TIMEOUT = 5


def tell(path: str, body: dict[str, str]) -> bool:
    """Ask the agent's service to do some work, and say whether it was reached."""
    url = os.getenv("UNDERCOVER_AGENT", DEFAULT_URL)
    try:
        return httpx.post(f"{url}{path}", json=body, timeout=TIMEOUT).is_success
    except httpx.HTTPError:
        return False


def resume(claim_id: str) -> None:
    """Tell the agent a claim is signed off. If it's away, it picks it up next time."""
    tell(f"/claims/{claim_id}/resume", {})
