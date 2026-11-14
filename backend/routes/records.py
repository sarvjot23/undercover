"""Our records on their own: a policy, a customer and their history, who is signed
in, and the payouts over the approval limit."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Table, select

from backend import keys, settings
from backend.auth import SignedIn
from backend.db import SingleStatementDb, customers, payments, plans, policies
from backend.db import claims as claim_table
from backend.rules import standing_of, standing_query

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


@router.get("/me", operation_id="who_am_i")
def who_am_i(handler: SignedIn) -> dict[str, Any]:
    """Get the handler signed in, with whether they can sign off over the limit."""
    return handler


def in_queue(conn: SingleStatementDb, customer_id: str) -> list[dict[str, Any]]:
    """A customer's claims in our queue with where each stands, never a copy."""
    query = (
        standing_query()
        .where(claim_table.c.evaluation_id.is_(None))
        .order_by(claim_table.c.claim_id)
    )
    found = []
    for row in conn.execute(query).mappings():
        claim = json.loads(row["body"])
        if claim["customer_id"] != customer_id:
            continue
        decision = standing_of(row)["decision"]
        found.append(
            {
                "claim_id": claim["claim_id"],
                "claim_type": claim["claim_type"],
                "summary": claim["summary"],
                "amount_claimed": claim["amount_claimed"],
                "status": row["status"],
                "decision": decision["decision"] if decision else None,
                "payout": decision["payout"] if decision else None,
            }
        )
    return found


@router.get(
    "/customers/named/{name}", operation_id="find_customers", dependencies=keys.HANDLER
)
def find_customers(name: str, conn: SingleStatementDb) -> list[dict[str, Any]]:
    """Find the customers whose name has every word given, in any case."""
    words = name.lower().split()
    found = [
        {
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "customer_since": customer["customer_since"],
        }
        for customer in map(
            json.loads, conn.execute(select(customers.c.body)).scalars()
        )
        if all(word in customer["name"].lower() for word in words)
    ]
    return sorted(found, key=lambda customer: customer["name"])


@router.get(
    "/customers/{customer_id}", operation_id="get_customer", dependencies=keys.HANDLER
)
def get_customer(customer_id: str, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a customer with their policies, earlier claims and claims in our queue."""
    customer = find(conn, customers, "customer_id", customer_id)
    held = [
        policy
        for policy in map(json.loads, conn.execute(select(policies.c.body)).scalars())
        if policy["customer_id"] == customer_id
    ]
    return {
        **customer,
        "policies": held,
        "claims_in_queue": in_queue(conn, customer_id),
    }


@router.get(
    "/payouts/over-limit",
    operation_id="count_payouts_over_limit",
    dependencies=keys.HANDLER,
)
def count_payouts_over_limit(conn: SingleStatementDb) -> dict[str, Any]:
    """Count the claims in our queue paid over the limit, and those signed off."""
    limit = settings.current(conn).approval_limit
    query = (
        select(payments.c.claim_id, payments.c.signed_off_by)
        .join(claim_table, claim_table.c.claim_id == payments.c.claim_id)
        .where(claim_table.c.evaluation_id.is_(None), payments.c.amount > limit)
        .order_by(payments.c.claim_id)
    )
    paid = conn.execute(query).mappings().all()
    return {
        "approval_limit": limit,
        "paid_over_limit": len(paid),
        "signed_off": sum(row["signed_off_by"] is not None for row in paid),
        "claim_ids": [row["claim_id"] for row in paid],
    }
