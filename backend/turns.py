"""Requests take turns: a swarm of claim agents can't starve the backend of threads.

FastAPI checks out a request's connection in a worker thread, then runs the handler
in another. With 25 agents, every worker thread could end up waiting for one of the
4 connections while the requests that hold them wait for a thread to finish in.
Here, requests beyond the limit wait on the event loop, where waiting holds no thread.
"""

import asyncio
from typing import Any
from weakref import WeakKeyDictionary

from backend.db import MAX_CONNECTIONS

# Twice the connections, so a connection is never left waiting for a request.
LIMIT = 2 * MAX_CONNECTIONS

Scope = dict[str, Any]

turns: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    WeakKeyDictionary()
)


def turn() -> asyncio.Semaphore:
    """The turns for this event loop: the app's own, or one of a test's."""
    loop = asyncio.get_running_loop()
    if loop not in turns:
        turns[loop] = asyncio.Semaphore(LIMIT)
    return turns[loop]


class TakingTurns:
    """ASGI middleware: at most LIMIT requests inside the app at once."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        async with turn():
            await self.app(scope, receive, send)
