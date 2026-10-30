"""The claims queue: a claim in full, its steps, deciding and paying."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from backend import db, leases
from backend.db import Db, customers, decisions, handlers, payments, sign_offs, steps
from backend.db import claims as claim_table
from backend.payout import Payout, work_out_payout
from backend.rules import (
    APPROVAL_LIMIT,
    add,
    fail,
    find_claim,
    find_standing,
    insert_once,
    move,
    record,
    standing,
    standing_of,
    standing_query,
)
from backend.schemas import (
    ClaimStart,
    Decision,
    Failure,
    Lease,
    Payment,
    PayoutRequest,
    SignOff,
    Step,
)

router = APIRouter(prefix="/api/claims")


@router.get("", operation_id="list_claims")
def list_claims(conn: Db) -> list[dict[str, Any]]:
    """List the claims queue with where each claim stands."""
    names = {
        row["customer_id"]: json.loads(row["body"])["name"]
        for row in conn.execute(select(customers)).mappings()
    }
    claims = []
    query = standing_query().order_by(claim_table.c.claim_id)
    for row in conn.execute(query).mappings():
        claim = json.loads(row["body"])
        found = standing_of(row)
        decision = found["decision"]
        claims.append(
            {
                "claim_id": claim["claim_id"],
                "customer_name": names[claim["customer_id"]],
                "claim_type": claim["claim_type"],
                "summary": claim["summary"],
                "amount_claimed": claim["amount_claimed"],
                "submitted_on": claim["submitted_on"],
                "status": found["status"],
                "attempts": found["attempts"],
                "thread_id": found["thread_id"],
                "agent_working": found["agent_working"],
                "decision": decision["decision"] if decision else None,
                "payout": decision["payout"] if decision else None,
                "signed_off": found["sign_off"] is not None,
            }
        )
    return claims


@router.get("/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, conn: Db) -> dict[str, Any]:
    """Get a claim with its policy, plan, customer, decision and payment."""
    row = find_standing(conn, claim_id)
    claim = json.loads(row["body"])
    policy = record(conn, "policy", claim["policy_id"])
    customer = record(conn, "customer", claim["customer_id"])
    return {
        **claim,
        **standing_of(row),
        "policy": policy,
        "plan": record(conn, "plan", policy["plan"]),
        "customer": {
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "customer_since": customer["customer_since"],
            "previous_claims": customer["previous_claims"],
        },
    }


@router.get("/{claim_id}/standing", operation_id="get_standing")
def get_standing(claim_id: str, conn: Db) -> dict[str, Any]:
    """Get where a claim stands, with its decision, sign-off and payment."""
    return standing(conn, claim_id)


@router.get("/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: Db) -> list[dict[str, Any]]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(conn, claim_id)
    query = select(steps).where(steps.c.claim_id == claim_id).order_by(steps.c.step_id)
    return [dict(row) for row in conn.execute(query).mappings()]


@router.post("/{claim_id}/lease", operation_id="take_claim_lease")
def take_claim_lease(claim_id: str, lease: Lease, conn: Db) -> dict[str, str]:
    """Take or renew the lease on a claim, unless another worker holds it."""
    find_claim(conn, claim_id)
    if not leases.take(conn, claim_table, claim_id, lease.worker):
        raise HTTPException(409, f"Another worker is on claim {claim_id}")
    conn.commit()
    return {"claim_id": claim_id, "worker": lease.worker}


@router.post("/{claim_id}/lease/release", operation_id="release_claim_lease")
def release_claim_lease(claim_id: str, lease: Lease, conn: Db) -> dict[str, str]:
    """Give up the lease on a claim."""
    leases.release(conn, claim_table, claim_id, lease.worker)
    conn.commit()
    return {"claim_id": claim_id}


@router.post("/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, start: ClaimStart, conn: Db) -> dict[str, str]:
    """Mark a waiting claim as in progress on a thread."""
    move(conn, claim_id, "waiting", "in_progress")
    conn.execute(
        claim_table.update()
        .where(claim_table.c.claim_id == claim_id)
        .values(thread_id=start.thread_id)
    )
    conn.commit()
    return {"claim_id": claim_id, "status": "in_progress"}


@router.post("/{claim_id}/steps", operation_id="add_step")
def add_step(claim_id: str, step: Step, conn: Db) -> dict[str, str]:
    """Record one step of the agent's work on a claim, once for each key."""
    find_claim(conn, claim_id)
    add(conn, claim_id, step.kind, step.text, step.key)
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


def next_status(decision: Decision) -> str:
    """Say where a decision leaves a claim: an approval stays in progress until paid."""
    if decision.decision != "approve":
        return "decided"
    if decision.payout > APPROVAL_LIMIT:
        return "awaiting_sign_off"
    return "in_progress"


@router.post("/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, decision: Decision, conn: Db) -> dict[str, Any]:
    """Record the decision on a claim in progress; a repeat of it counts as done."""
    if decision.decision != "approve" and decision.payout != 0:
        raise HTTPException(422, "A decline or a referral pays $0")
    payout = round(decision.payout, 2)
    found = standing(conn, claim_id)
    recorded = found["decision"]
    if recorded:
        if (recorded["decision"], recorded["payout"]) == (decision.decision, payout):
            return found
        raise HTTPException(409, f"Claim {claim_id} already has a different decision")
    move(conn, claim_id, "in_progress", next_status(decision))
    insert_once(
        conn,
        decisions,
        claim_id=claim_id,
        decision=decision.decision,
        payout=payout,
        reasons=decision.reasons,
        policy_section=decision.policy_section,
        decided_at=db.now(),
    )
    conn.commit()
    return standing(conn, claim_id)


@router.post("/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, payment: Payment, conn: Db) -> dict[str, Any]:
    """Pay an approved payout, once, and only after any sign-off it needs."""
    found = standing(conn, claim_id)
    decision = found["decision"]
    if decision is None or decision["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} has no approved payout")
    amount = round(payment.amount, 2)
    if found["payment"]:
        if found["payment"]["amount"] == amount:
            return found
        raise HTTPException(409, f"Claim {claim_id} is already paid")
    sign_off = found["sign_off"]
    if decision["payout"] > APPROVAL_LIMIT and sign_off is None:
        raise HTTPException(
            409, f"A payout over ${APPROVAL_LIMIT:,.2f} waits for a handler's sign-off"
        )
    if amount != decision["payout"]:
        raise HTTPException(
            409, f"The amount must be the approved payout, ${decision['payout']:,.2f}"
        )
    move(conn, claim_id, "in_progress", "decided")
    insert_once(
        conn,
        payments,
        claim_id=claim_id,
        amount=amount,
        signed_off_by=sign_off["handler_id"] if sign_off else None,
        signed_off_at=sign_off["signed_off_at"] if sign_off else None,
        paid_at=db.now(),
    )
    conn.commit()
    return standing(conn, claim_id)


@router.post("/{claim_id}/sign-off", operation_id="sign_off")
def sign_off(claim_id: str, sign_off: SignOff, conn: Db) -> dict[str, Any]:
    """Record a handler's sign-off on a payout over the limit; the agent pays it."""
    query = select(handlers.c.handler_id).where(
        handlers.c.handler_id == sign_off.handler_id
    )
    if conn.execute(query).first() is None:
        raise HTTPException(404, f"No handler {sign_off.handler_id}")
    move(conn, claim_id, "awaiting_sign_off", "in_progress")
    insert_once(
        conn,
        sign_offs,
        claim_id=claim_id,
        handler_id=sign_off.handler_id,
        signed_off_at=db.now(),
    )
    conn.commit()
    return standing(conn, claim_id)


@router.post("/{claim_id}/fail", operation_id="fail_claim")
def fail_claim(claim_id: str, failure: Failure, conn: Db) -> dict[str, str]:
    """Count a failed attempt: back to the queue, or to a handler the second time."""
    status = fail(conn, claim_id, failure.reason)
    conn.commit()
    return {"claim_id": claim_id, "status": status}
