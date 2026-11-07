"""Who is calling: the agent's side with its API key, or a signed-in handler.

The key is read from the request itself, so it adds no input to any operation.
It never stands in for a handler: the handlers' actions check only the sign-in.
"""

import os
import secrets

from fastapi import Depends, HTTPException, Request

from backend import auth

HEADER = "X-API-Key"
NO_KEY = "The agent's API key is missing or wrong"


def has_key(request: Request) -> bool:
    """Whether the request carries the agent's key; none is right if it isn't set."""
    expected = os.getenv("UNDERCOVER_API_KEY", "")
    sent = request.headers.get(HEADER, "")
    return bool(expected) and secrets.compare_digest(sent.encode(), expected.encode())


def agent_key(request: Request) -> None:
    """The agent's side only, or 401."""
    if not has_key(request):
        raise HTTPException(401, NO_KEY)


def reader(request: Request) -> None:
    """The agent's key or a signed-in handler, or 401."""
    if has_key(request):
        return
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, auth.NOT_SIGNED_IN)
    if auth.find_handler(auth.email_in(token)) is None:
        raise HTTPException(401, auth.NOT_SIGNED_IN)


AGENT = [Depends(agent_key)]
READ = [Depends(reader)]
HANDLER = [Depends(auth.signed_in)]
