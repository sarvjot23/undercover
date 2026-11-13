"""Getting the agent ready on its first request, once in its process.

Nothing happens on import: on Runtime's platform version V2 every session starts from
one snapshot, so a key fetched or a connection opened before the first request would
be shared by every session.
"""

import os
import random
import re
import threading

from bedrock_agentcore.identity.auth import requires_api_key

from agent import checkpoints

KEY_MISSING = "UNDERCOVER_API_KEY is missing, so the backend would refuse the agent"
# The deployment names each credential's provider in AgentCore Identity.
CREDENTIAL = re.compile(r"^AGENTCORE_CREDENTIAL_(\w+)_NAME$")

lock = threading.Lock()
state = {"ready": False}


def on_runtime() -> bool:
    """Whether the agent runs on AgentCore Runtime: its deployment names credentials."""
    return any(CREDENTIAL.match(name) for name in os.environ)


def fetch(provider: str) -> str:
    """Fetch a credential's value from AgentCore Identity, as this request's agent."""

    @requires_api_key(provider_name=provider)
    def value(*, api_key: str = "") -> str:
        return api_key

    return value()


def get_ready() -> None:
    """Get ready once: on Runtime, reseed the random numbers and fetch each
    credential into its setting; then check the key and open the checkpoint pool.
    Nothing is marked stopped: work that went quiet is the app's to stop.

    If it fails, the request answers with the error and the next one tries again.
    """
    with lock:
        if state["ready"]:
            return
        if on_runtime():
            random.seed()
            for name, provider in list(os.environ.items()):
                found = CREDENTIAL.match(name)
                if found:
                    os.environ[found.group(1)] = fetch(provider)
        if not os.getenv("UNDERCOVER_API_KEY"):
            raise RuntimeError(KEY_MISSING)
        url = os.getenv("DATABASE_URL")
        if url:
            checkpoints.pool(url)
        state["ready"] = True
