"""The route the claim agent's tools take: the Gateway when it's set up, or direct."""

import os
from typing import Any, Protocol

from agent.direct import DEFAULT_CONTEXT, Direct
from agent.gateway import Gateway


class Route(Protocol):
    """How the agent reaches the app and the context layer for its tools."""

    name: str

    def tool_name(self, target: str, operation: str) -> str: ...

    def call(self, target: str, operation: str, arguments: dict[str, Any]) -> str: ...


def choose() -> Route:
    """Read the settings now, not at import: the command line loads .env late."""
    gateway_url = os.getenv("UNDERCOVER_GATEWAY_URL")
    if gateway_url:
        return Gateway(gateway_url)
    return Direct(os.getenv("UNDERCOVER_CONTEXT") or DEFAULT_CONTEXT)
