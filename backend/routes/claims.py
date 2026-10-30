"""The claims queue: a claim in full, its steps, deciding and paying."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from backend import db
from backend.db import Db, customers, decisions, handlers, payments, steps
from backend.db import claims as claim_table
from backend.payout import Payout, work_out_payout
from backend.rules import (
    APPROVAL_LIMIT,
    add,
    agent_working,
    decision_of,
    fail,
    find_claim,
    is_working,
    last_steps,
    move,
    record,
)
from backend.schemas import Decision, Failure, Payment, PayoutRequest, SignOff, Step

router = APIRouter(prefix="/api/claims")


@router.get("", operation_id="list_claims")
def list_claims(conn: Db) -> list[dict[str, Any]]:
    """List the claims queue with where each claim stands."""
    names = {
        row["customer_id"]: json.loads(row["body"])["name"]
        for row in conn.execute(select(customers)).mappings()
    }
    found = {row["claim_id"]: row for row in conn.execute(select(decisions)).mappings()}
    latest = last_steps(conn)
    query = select(claim_table).order_by(claim_table.c.claim_id)
    claims = []
    for row in conn.execute(query).mappings():
        claim = json.loads(row["body"])
        decision = found.get(row["claim_id"])
        claims.append(
            {
                "claim_id": claim["claim_id"],
                "customer_name": names[claim["customer_id"]],
                "claim_type": claim["claim_type"],
                "summary": claim["summary"],
                "amount_claimed": claim["amount_claimed"],
                "submitted_on": claim["submitted_on"],
                "status": row["status"],
                "attempts": row["attempts"],
                "agent_working": is_working(row["status"], latest.get(row["claim_id"])),
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
    query = select(payments).where(payments.c.claim_id == claim_id)
    payment = conn.execute(query).mappings().first()
    return {
        **claim,
        "status": row["status"],
        "attempts": row["attempts"],
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
    query = select(steps).where(steps.c.claim_id == claim_id).order_by(steps.c.step_id)
    return [dict(row) for row in conn.execute(query).mappings()]


@router.post("/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, conn: Db) -> dict[str, str]:
    """Mark a waiting claim as in progress."""
    move(conn, claim_id, "waiting", "in_progress")
    conn.commit()
    return {"claim_id": claim_id, "status": "in_progress"}


@router.post("/{claim_id}/steps", operation_id="add_step")
def add_step(claim_id: str, step: Step, conn: Db) -> dict[str, str]:
    """Record one step of the agent's work on a claim."""
    find_claim(conn, claim_id)
    add(conn, claim_id, step.kind, step.text)
    conn.commit()
    return {"claim_id": claim_id, "kind": step.kind}


@router.post("/{claim_id}/payout", operation_id="calculate_payout")
def calculate_payout(claim_id: str, request: PayoutRequest, conn: Db) -> Payout:
    """Work out the payout on an approved claim with our payout rules."""
    policy_id = json.loads(find_claim(conn, claim_id)["body"])["policy_id"]
    return work_out_payout(
        record(conn, "policy", policy_id),
        request.benefit,
        request.lines,
        request.paid_by_others,
    )


@router.post("/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, decision: Decision, conn: Db) -> dict[str, str]:
    """Record the decision on a claim that is in progress."""
    approve = decision.decision == "approve"
    if not approve and decision.payout != 0:
        raise HTTPException(422, "A decline or a referral pays $0")
    over_limit = approve and decision.payout > APPROVAL_LIMIT
    status = "awaiting_sign_off" if over_limit else "decided"
    move(conn, claim_id, "in_progress", status)
    conn.execute(
        decisions.insert().values(
            claim_id=claim_id,
            decision=decision.decision,
            payout=round(decision.payout, 2),
            reasons=decision.reasons,
            policy_section=decision.policy_section,
            decided_at=db.now(),
        )
    )
    conn.commit()
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
    query = select(payments.c.claim_id).where(payments.c.claim_id == claim_id)
    if conn.execute(query).first():
        raise HTTPException(409, f"Claim {claim_id} is already paid")
    if round(payment.amount, 2) != decision["payout"]:
        raise HTTPException(
            409, f"The amount must be the approved payout, ${decision['payout']:,.2f}"
        )
    conn.execute(
        payments.insert().values(
            claim_id=claim_id, amount=decision["payout"], paid_at=db.now()
        )
    )
    conn.commit()
    return {"claim_id": claim_id, "amount": decision["payout"]}


@router.post("/{claim_id}/sign-off", operation_id="sign_off")
def sign_off(claim_id: str, sign_off: SignOff, conn: Db) -> dict[str, Any]:
    """Sign off a payout over the approval limit and release the payment."""
    query = select(handlers.c.handler_id).where(
        handlers.c.handler_id == sign_off.handler_id
    )
    if conn.execute(query).first() is None:
        raise HTTPException(404, f"No handler {sign_off.handler_id}")
    move(conn, claim_id, "awaiting_sign_off", "decided")
    decision = decision_of(conn, claim_id)
    payout = decision["payout"] if decision else 0.0
    conn.execute(
        payments.insert().values(
            claim_id=claim_id,
            amount=payout,
            signed_off_by=sign_off.handler_id,
            paid_at=db.now(),
        )
    )
    conn.commit()
    return {"claim_id": claim_id, "amount": payout, "status": "decided"}


@router.post("/{claim_id}/fail", operation_id="fail_claim")
def fail_claim(claim_id: str, failure: Failure, conn: Db) -> dict[str, str]:
    """Count a failed attempt: back to the queue, or to a handler the second time."""
    status = fail(conn, claim_id, failure.reason)
    conn.commit()
    return {"claim_id": claim_id, "status": status}
