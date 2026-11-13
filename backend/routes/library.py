"""What the agent and the handlers read: the policy wording and the handlers."""

import json
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from backend import keys
from backend.db import SingleStatementDb, documents, handlers

router = APIRouter(prefix="/api")


@router.get(
    "/policy-wording", operation_id="get_policy_wording", dependencies=keys.HANDLER
)
def get_policy_wording(conn: SingleStatementDb) -> dict[str, str]:
    """Get the policy wording that decisions follow."""
    query = select(documents.c.text).where(documents.c.document == "policy_wording")
    return {"text": conn.execute(query).scalar_one()}


@router.get("/handlers", operation_id="list_handlers", dependencies=keys.HANDLER)
def list_handlers(conn: SingleStatementDb) -> list[dict[str, Any]]:
    """List the claims handlers."""
    return [
        json.loads(body) for body in conn.execute(select(handlers.c.body)).scalars()
    ]
