"""A stand-in for the AgentCore Gateway: an MCP server that names each tool as the
Gateway does, passes calls on to the app, and refuses what its policy forbids with
an MCP error, as the Gateway's Policy does."""

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from starlette.applications import Starlette
from starlette.routing import Route

from agent.direct import APP, OPERATIONS, Direct
from agent.mcp_bridge import Refused

Forbid = Callable[[str, dict[str, Any]], bool]


class Handle:
    """The MCP endpoint as an ASGI app."""

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self.manager.handle_request(scope, receive, send)


def gateway(forbid: Forbid) -> Starlette:
    """The stand-in, with a rule for the calls its policy forbids."""
    server = Server("standin-gateway")
    calls: list[str] = []

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=f"{APP}___{name}", inputSchema={"type": "object"})
            for name in OPERATIONS
        ]  # The context layer's tools are passed on too, without being listed.

    async def call_tool(request: types.CallToolRequest) -> types.ServerResult:
        name = request.params.name
        arguments = request.params.arguments or {}
        calls.append(name)
        if forbid(name, arguments):
            raise McpError(
                types.ErrorData(code=-32002, message="Tool Execution Denied: forbid")
            )
        target, operation = name.split("___")
        # The stand-in reaches the context layer the tests serve.
        route = Direct(os.environ["UNDERCOVER_CONTEXT"])
        try:
            # On a thread: the route runs its own event loop, and this is inside one.
            found = await anyio.to_thread.run_sync(
                route.call, target, operation, arguments
            )
            text, refused = found, False
        except Refused as refusal:
            text, refused = refusal.reason, True
        return types.ServerResult(
            types.CallToolResult(
                content=[types.TextContent(type="text", text=text)], isError=refused
            )
        )

    server.request_handlers[types.CallToolRequest] = call_tool
    manager = StreamableHTTPSessionManager(
        app=server, stateless=True, json_response=True
    )

    @asynccontextmanager
    async def lifespan(_: Starlette):  # noqa: ANN202
        async with manager.run():
            yield

    app = Starlette(routes=[Route("/mcp", endpoint=Handle(manager))], lifespan=lifespan)
    app.state.calls = calls
    return app
