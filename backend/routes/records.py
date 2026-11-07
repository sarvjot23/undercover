"""A customer's policy and claim history, each on its own, as get_claim shows them."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Table, select

from backend import keys
from backend.db import SingleStatementDb, customers, plans, policies

router = APIRouter(prefix="/api")


def find(conn: SingleStatementDb, table: Table, column: str, key: str) -> Any:
    """A stored record by its id, or 404."""
    body = conn.execute(select(table.c.body).where(table.c[column] == key)).scalar()
    if body is None:
        raise HTTPException(404, f"No {column.removesuffix('_id')} {key}")
    return json.loads(body)


@router.get("/policies/{policy_id}", operation_id="get_policy", dependencies=keys.READ)
def get_policy(policy_id: str, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a customer's policy with its plan's limits."""
    policy = find(conn, policies, "policy_id", policy_id)
    return {**policy, "plan_limits": find(conn, plans, "plan", policy["plan"])}


@router.get(
    "/customers/{customer_id}/claims",
    operation_id="get_claim_history",
    dependencies=keys.READ,
)
def get_claim_history(customer_id: str, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a customer's claim history with UnderCover."""
    customer = find(conn, customers, "customer_id", customer_id)
    return {
        "customer_id": customer["customer_id"],
        "name": customer["name"],
        "customer_since": customer["customer_since"],
        "previous_claims": customer["previous_claims"],
    }
