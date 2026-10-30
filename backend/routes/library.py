"""What the agent and the handlers read: the wording, instructions and handlers."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from backend import db
from backend.db import Db, handlers

INSTRUCTIONS = Path(__file__).parent.parent / "instructions"

router = APIRouter(prefix="/api")


@router.get("/policy-wording", operation_id="get_policy_wording")
def get_policy_wording() -> dict[str, str]:
    """Get the policy wording that decisions follow."""
    return {"text": (db.DATA / "policy_wording.md").read_text(encoding="utf-8")}


@router.get("/instructions", operation_id="get_instructions")
def get_instructions() -> dict[str, str]:
    """Get the UnderCover Agent's instructions for the queue and for a claim."""
    return {
        name: (INSTRUCTIONS / f"{name}.md").read_text(encoding="utf-8")
        for name in ("queue", "claim")
    }


@router.get("/handlers", operation_id="list_handlers")
def list_handlers(conn: Db) -> list[dict[str, Any]]:
    """List the claims handlers."""
    return [
        json.loads(body) for body in conn.execute(select(handlers.c.body)).scalars()
    ]
