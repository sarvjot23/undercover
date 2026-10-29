"""The claims queue: a claim in full, its steps, deciding and paying."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from backend import db
from backend.db import Db
from backend.rules import (
    APPROVAL_LIMIT,
    add,
    agent_working,
    decision_of,
    find_claim,
    move,
    record,
)
from backend.schemas import Decision, Failure, Payment, SignOff, Step

router = APIRouter(prefix="/api/claims")


@router.get("", operation_id="list_claims")
def list_claims(conn: Db) -> list[dict[str, Any]]:
    """List the claims queue with where each claim stands."""
    names = {
        row["customer_id"]: json.loads(row["body"])["name"]
        for row in conn.execute("SELECT * FROM customers")
    }
    claims = []
    for row in conn.execute("SELECT * FROM claims ORDER BY claim_id"):
        claim = json.loads(row["body"])
        decision = decision_of(conn, row["claim_id"])
        claims.append(
            {
                "claim_id": claim["claim_id"],
                "customer_name": names[claim["customer_id"]],
                "claim_type": claim["claim_type"],
                "summary": claim["summary"],
                "amount_claimed": claim["amount_claimed"],
                "submitted_on": claim["submitted_on"],
                "status": row["status"],
                "agent_working": agent_working(conn, row),
                "decision": decision["decision"] if decision else None,
                "payout": decision["payout"] if decision else None,
            }
        )
    return claims


@router.get("/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, conn: Db) -> dict[str, Any]:
    """Get a claim with its policy, plan, customer, decision and payment."""
    row = find_claim(conn, claim_id)
    claim = json.loads(row["body"])
    policy = record(conn, "policy", claim["policy_id"])
    customer = record(conn, "customer", claim["customer_id"])
    payment = conn.execute(
        "SELECT * FROM payments WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    return {
        **claim,
        "status": row["status"],
        "agent_working": agent_working(conn, row),
        "policy": policy,
        "plan": record(conn, "plan", policy["plan"]),
        "customer": {
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "customer_since": customer["customer_since"],
            "previous_claims": customer["previous_claims"],
        },
        "decision": decision_of(conn, claim_id),
        "payment": dict(payment) if payment else None,
    }


@router.get("/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: Db) -> list[dict[str, Any]]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(conn, claim_id)
    rows = conn.execute(
        "SELECT * FROM steps WHERE claim_id = ? ORDER BY step_id", (claim_id,)
    )
    return [dict(row) for row in rows]


@router.post("/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, conn: Db) -> dict[str, str]:
    """Mark a waiting claim as in progress."""
    with conn:
        move(conn, claim_id, "waiting", "in_progress")
    return {"claim_id": claim_id, "status": "in_progress"}


@router.post("/{claim_id}/steps", operation_id="add_step")
def add_step(claim_id: str, step: Step, conn: Db) -> dict[str, str]:
    """Record one step of the agent's work on a claim."""
    find_claim(conn, claim_id)
    with conn:
        add(conn, claim_id, step.kind, step.text)
    return {"claim_id": claim_id, "kind": step.kind}


@router.post("/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, decision: Decision, conn: Db) -> dict[str, str]:
    """Record the decision on a claim that is in progress."""
    approve = decision.decision == "approve"
    if not approve and decision.payout != 0:
        raise HTTPException(422, "A decline or a referral pays $0")
    over_limit = approve and decision.payout > APPROVAL_LIMIT
    status = "awaiting_sign_off" if over_limit else "decided"
    with conn:
        move(conn, claim_id, "in_progress", status)
        conn.execute(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?)",
            (
                claim_id,
                decision.decision,
                round(decision.payout, 2),
                decision.reasons,
                decision.policy_section,
                db.now(),
            ),
        )
    return {"claim_id": claim_id, "status": status}


@router.post("/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, payment: Payment, conn: Db) -> dict[str, Any]:
    """Pay a claim's approved payout, unless it waits for a handler's sign-off."""
    row = find_claim(conn, claim_id)
    if row["status"] == "awaiting_sign_off":
        raise HTTPException(
            409, f"A payout over ${APPROVAL_LIMIT:,.2f} waits for a handler's sign-off"
        )
    decision = decision_of(conn, claim_id)
    if decision is None or decision["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} has no approved payout")
    if conn.execute(
        "SELECT 1 FROM payments WHERE claim_id = ?", (claim_id,)
    ).fetchone():
        raise HTTPException(409, f"Claim {claim_id} is already paid")
    if round(payment.amount, 2) != decision["payout"]:
        raise HTTPException(
            409, f"The amount must be the approved payout, ${decision['payout']:,.2f}"
        )
    with conn:
        conn.execute(
            "INSERT INTO payments VALUES (?, ?, NULL, ?)",
            (claim_id, decision["payout"], db.now()),
        )
    return {"claim_id": claim_id, "amount": decision["payout"]}


@router.post("/{claim_id}/sign-off", operation_id="sign_off")
def sign_off(claim_id: str, sign_off: SignOff, conn: Db) -> dict[str, Any]:
    """Sign off a payout over the approval limit and release the payment."""
    if (
        conn.execute(
            "SELECT 1 FROM handlers WHERE handler_id = ?", (sign_off.handler_id,)
        ).fetchone()
        is None
    ):
        raise HTTPException(404, f"No handler {sign_off.handler_id}")
    with conn:
        move(conn, claim_id, "awaiting_sign_off", "decided")
        payout = conn.execute(
            "SELECT payout FROM decisions WHERE claim_id = ?", (claim_id,)
        ).fetchone()["payout"]
        conn.execute(
            "INSERT INTO payments VALUES (?, ?, ?, ?)",
            (claim_id, payout, sign_off.handler_id, db.now()),
        )
    return {"claim_id": claim_id, "amount": payout, "status": "decided"}


@router.post("/{claim_id}/fail", operation_id="fail_claim")
def fail_claim(claim_id: str, failure: Failure, conn: Db) -> dict[str, str]:
    """Send a claim back to waiting after the agent's run failed."""
    with conn:
        move(conn, claim_id, "in_progress", "waiting")
        add(conn, claim_id, "error", failure.reason)
    return {"claim_id": claim_id, "status": "waiting"}
