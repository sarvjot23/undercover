"""MCP tool calls from the synchronous agent, over streamable HTTP.

Each call opens a session on a new event loop of its own and closes it, without
making it the thread's loop: asyncio.run would leave the main thread with no loop,
which Mangum then asks for. The Gateway and the context layer are stateless, so a
session for each call is enough.
"""

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError

TIMEOUT = 150


class Refused(Exception):
    """A tool call that was refused, with who refused it and why."""

    def __init__(self, by: str, reason: str) -> None:
        super().__init__(f"Refused by {by}: {reason}")
        self.by = by
        self.reason = reason


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to the end on a loop of its own."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


@dataclass(frozen=True)
class Server:
    """An MCP server: its address, how requests to it are signed, and its name."""

    url: str
    auth: httpx.Auth | None
    name: str


async def call_async(server: Server, tool: str, arguments: dict[str, Any]) -> Any:
    """Call one tool and give back its result, or the server's MCP error.

    The error is caught inside the session: raised through the transport's task
    group, it would come out wrapped in an exception group.
    """
    http = httpx.AsyncClient(auth=server.auth, timeout=TIMEOUT)
    async with (
        http,
        streamable_http_client(server.url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        try:
            return await session.call_tool(tool, arguments)
        except McpError as error:
            return error


def call(server: Server, tool: str, arguments: dict[str, Any], owner: str) -> str:
    """Call one tool and give its answer's text.

    An error result is a refusal by the tool's owner, such as the app; an MCP error
    is a refusal by the server itself, such as the Gateway's Policy.
    """
    result = run(call_async(server, tool, arguments))
    if isinstance(result, McpError):
        raise Refused(server.name, result.error.message)
    text = "\n".join(part.text for part in result.content if part.type == "text")
    if result.isError:
        raise Refused(owner, text)
    return text
