"""The direct route: the app's operations with the agent's key, and the context layer
over MCP without signing. Used when there's no Gateway, such as on the laptop."""

from typing import Any

from agent import client, mcp_bridge
from agent.mcp_bridge import Refused

APP = "undercover-app"
CONTEXT = "undercover-context"
DEFAULT_CONTEXT = "http://127.0.0.1:8006/mcp"

# Each of the app's operations for the claim agent, as its API document has it: the
# method, the path, and the inputs that go in the path; any other inputs are the body.
OPERATIONS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "get_claim": ("GET", "/api/claims/{claim_id}", ("claim_id",)),
    "get_policy": ("GET", "/api/policies/{policy_id}", ("policy_id",)),
    "get_claim_history": (
        "GET",
        "/api/customers/{customer_id}/claims",
        ("customer_id",),
    ),
    "calculate_payout": ("POST", "/api/claims/{claim_id}/payout", ("claim_id",)),
    "record_decision": ("POST", "/api/claims/{claim_id}/decision", ("claim_id",)),
    "pay_claim": ("POST", "/api/claims/{claim_id}/payment", ("claim_id",)),
}


class Direct:
    """The app through the agent's client, and the context layer at its address."""

    name = "direct"

    def __init__(self, context_url: str) -> None:
        self.context_url = context_url

    def tool_name(self, target: str, operation: str) -> str:
        """Tools keep their own names on this route."""
        return operation

    def call(self, target: str, operation: str, arguments: dict[str, Any]) -> str:
        """Call one operation of the app or the context layer, or raise Refused."""
        if target == CONTEXT:
            server = mcp_bridge.Server(self.context_url, None, "the context layer")
            return mcp_bridge.call(server, operation, arguments, "the context layer")
        method, path, in_path = OPERATIONS[operation]
        body = {k: v for k, v in arguments.items() if k not in in_path}
        with client.backend() as backend:
            response = backend.request(
                method,
                path.format(**arguments),
                json=body if method == "POST" else None,
            )
        if not response.is_success:
            raise Refused(
                "the app", f"({response.status_code}) {response.json()['detail']}"
            )
        return response.text
