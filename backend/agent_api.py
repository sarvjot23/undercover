"""The claim agent's own API: an OpenAPI document with its eight operations only.

The AgentCore Gateway makes a tool of each operation, so the dashboard's routes,
the evaluations and the sign-off stay out of the agent's reach. The deployment
adds the app's address, so the document has no servers.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute, iter_route_contexts

from backend import keys

OPERATIONS = {
    "get_claim",
    "get_policy",
    "get_claim_history",
    "search_documents",
    "read_section",
    "calculate_payout",
    "record_decision",
    "pay_claim",
}

router = APIRouter(prefix="/api/agent")


@router.get("/openapi.json", operation_id="get_agent_openapi", dependencies=keys.READ)
def get_agent_openapi(request: Request) -> dict[str, Any]:
    """Get the OpenAPI document of the claim agent's operations, for the Gateway."""
    routes = [
        context
        for context in iter_route_contexts(request.app.routes)
        if isinstance(context.route, APIRoute)
        and context.route.operation_id in OPERATIONS
    ]
    return get_openapi(title="UnderCover claim agent", version="1.0.0", routes=routes)
