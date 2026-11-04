"""Who is signed in: a handler's Supabase access token, checked on every action.

The project signs its tokens with asymmetric keys, so the backend needs no secret:
it checks each token against the public keys Supabase publishes. The agent's own
calls need no sign-in until Week 3.
"""

import json
import os
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from backend import db

AUDIENCE = "authenticated"
NOT_SIGNED_IN = "Sign in as a handler first"
CANT_SIGN_OFF = "can't sign off payouts over the limit"

bearer = HTTPBearer(auto_error=False, description="A handler's access token")
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


@lru_cache
def keys() -> jwt.PyJWKClient:
    """The project's public keys, from the Supabase address read once."""
    url = os.getenv("VITE_SUPABASE_URL", "")
    return jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json")


def email_in(token: str) -> str:
    """The email of a valid token, or 401."""
    try:
        key = keys().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, key.key, algorithms=[key.algorithm_name], audience=AUDIENCE
        )
    except jwt.PyJWTError:
        raise HTTPException(401, NOT_SIGNED_IN) from None
    return claims.get("email", "")


def find_handler(email: str) -> dict[str, Any] | None:
    """The handler with this email, if there is one."""
    query = select(db.handlers.c.body).where(db.handlers.c.email == email)
    with db.engine().connect() as conn:
        body = conn.execute(query).scalar()
    return json.loads(body) if body else None


def signed_in(credentials: Credentials) -> dict[str, Any]:
    """The handler signed in, or 401."""
    if credentials is None:
        raise HTTPException(401, NOT_SIGNED_IN)
    handler = find_handler(email_in(credentials.credentials))
    if handler is None:
        raise HTTPException(401, NOT_SIGNED_IN)
    return handler


SignedIn = Annotated[dict[str, Any], Depends(signed_in)]


def over_the_limit(action: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """A dependency: a handler who can sign off payouts over the limit, or 403."""

    def check(handler: SignedIn) -> dict[str, Any]:
        if not handler["can_approve_over_limit"]:
            why = f"{handler['name']} {CANT_SIGN_OFF}"
            raise HTTPException(
                403, why if action == "" else f"{why}, so can't {action}"
            )
        return handler

    return check


Approver = Annotated[dict[str, Any], Depends(over_the_limit(""))]
