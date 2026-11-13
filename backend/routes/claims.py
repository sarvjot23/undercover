"""The claims queue: a claim in full, its steps, deciding and paying."""

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import Connection, select

from backend import agent_service, db, keys, leases, settings
from backend.auth import Approver
from backend.db import (
    Db,
    SingleStatementDb,
    customers,
    decisions,
    payments,
    sign_offs,
    steps,
)
from backend.db import claims as claim_table
from backend.payout import Payout, work_out_payout
from backend.rules import (
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
    Hold,
    Lease,
    Payment,
    PayoutRequest,
    Step,
)

router = APIRouter(prefix="/api/claims")


@router.get("", operation_id="list_claims", dependencies=keys.READ)
def list_claims(conn: SingleStatementDb) -> list[dict[str, Any]]:
    """List the claims queue with where each claim stands, leaving out copies."""
    names = {
        row["customer_id"]: json.loads(row["body"])["name"]
        for row in conn.execute(select(customers)).mappings()
    }
    claims = []
    query = (
        standing_query()
        .where(claim_table.c.evaluation_id.is_(None))
        .order_by(claim_table.c.claim_id)
    )
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


@router.get("/{claim_id}", operation_id="get_claim", dependencies=keys.READ)
def get_claim(claim_id: str, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a claim with its policy, plan, customer, decision and payment."""
    row = find_standing(conn, claim_id)
    claim = json.loads(row["body"])
    policy = record(conn, "policy", claim["policy_id"])
    customer = record(conn, "customer", claim["customer_id"])
    # Whether this is an evaluation's copy is left out: the agent reads this.
    found = {k: v for k, v in standing_of(row).items() if k != "evaluation_id"}
    return {
        **claim,
        **found,
        "policy": policy,
        "plan": record(conn, "plan", policy["plan"]),
        "customer": {
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "customer_since": customer["customer_since"],
            "previous_claims": customer["previous_claims"],
        },
    }


@router.get("/{claim_id}/standing", operation_id="get_standing", dependencies=keys.READ)
def get_standing(claim_id: str, conn: SingleStatementDb) -> dict[str, Any]:
    """Get where a claim stands, with its decision, sign-off and payment."""
    return standing(conn, claim_id)


@router.get("/{claim_id}/steps", operation_id="list_steps", dependencies=keys.READ)
def list_steps(claim_id: str, conn: SingleStatementDb) -> list[dict[str, Any]]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(conn, claim_id)
    query = select(steps).where(steps.c.claim_id == claim_id).order_by(steps.c.step_id)
    return [dict(row) for row in conn.execute(query).mappings()]


@router.post(
    "/{claim_id}/lease", operation_id="take_claim_lease", dependencies=keys.AGENT
)
def take_claim_lease(
    claim_id: str, lease: Lease, conn: SingleStatementDb
) -> dict[str, str]:
    """Take or renew the lease on a claim, unless another worker holds it."""
    if not leases.take(conn, claim_table, claim_id, lease.worker):
        find_claim(conn, claim_id)
        raise HTTPException(409, f"Another worker is on claim {claim_id}")
    return {"claim_id": claim_id, "worker": lease.worker}


@router.post(
    "/{claim_id}/lease/release",
    operation_id="release_claim_lease",
    dependencies=keys.AGENT,
)
def release_claim_lease(
    claim_id: str, lease: Lease, conn: SingleStatementDb
) -> dict[str, str]:
    """Give up the lease on a claim."""
    leases.release(conn, claim_table, claim_id, lease.worker)
    return {"claim_id": claim_id}


@router.post("/{claim_id}/start", operation_id="start_claim", dependencies=keys.AGENT)
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


@router.post("/{claim_id}/steps", operation_id="add_step", dependencies=keys.AGENT)
def add_step(claim_id: str, step: Step, conn: SingleStatementDb) -> dict[str, str]:
    """Record one step of the agent's work on a claim, once for each key."""
    if not add(conn, claim_id, step.kind, step.text, step.key):
        find_claim(conn, claim_id)
    return {"claim_id": claim_id, "kind": step.kind}


@router.post(
    "/{claim_id}/payout", operation_id="calculate_payout", dependencies=keys.AGENT
)
def calculate_payout(claim_id: str, request: PayoutRequest, conn: Db) -> Payout:
    """Work out the payout on an approved claim with our payout rules."""
    policy = record(
        conn, "policy", json.loads(find_claim(conn, claim_id)["body"])["policy_id"]
    )
    return work_out_payout(
        {**policy, "plan_rules": record(conn, "plan", policy["plan"])},
        request.benefit,
        request.lines,
        request.paid_by_others,
        settings.current(conn).approval_limit,
    )


def next_status(decision: Decision, limit: float) -> str:
    """Say where a decision leaves a claim: an approval stays in progress until paid."""
    if decision.decision != "approve":
        return "decided"
    if decision.payout > limit:
        return "awaiting_sign_off"
    return "in_progress"


@router.post(
    "/{claim_id}/decision", operation_id="record_decision", dependencies=keys.AGENT
)
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
    limit = settings.current(conn).approval_limit
    move(conn, claim_id, "in_progress", next_status(decision, limit))
    insert_once(
        conn,
        decisions,
        claim_id=claim_id,
        decision=decision.decision,
        payout=payout,
        reasons=decision.reasons,
        policy_section=decision.policy_section,
        decided_at=db.now(),
        approval_limit=limit,
    )
    recorded = standing(conn, claim_id)
    conn.commit()
    return recorded


def settle_payment(conn: Connection, claim_id: str) -> None:
    """Mark a paid claim decided; run again after a restart, it changes nothing."""
    conn.execute(
        claim_table.update()
        .where(
            claim_table.c.claim_id == claim_id, claim_table.c.status == "in_progress"
        )
        .values(status="decided")
    )


@router.post("/{claim_id}/payment", operation_id="pay_claim", dependencies=keys.AGENT)
def pay_claim(
    claim_id: str, payment: Payment, conn: SingleStatementDb
) -> dict[str, Any]:
    """Pay an approved payout, once, and only after any sign-off it needs."""
    limit_now = settings.current(conn).approval_limit
    if payment.amount > limit_now:
        raise HTTPException(
            403, f"A payment over the approval limit of ${limit_now:,.2f} is refused"
        )
    found = standing(conn, claim_id)
    decision = found["decision"]
    if decision is None or decision["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} has no approved payout")
    amount = round(payment.amount, 2)
    paid = found["payment"]
    if paid:
        if paid["amount"] != amount:
            raise HTTPException(409, f"Claim {claim_id} is already paid")
    else:
        sign_off = found["sign_off"]
        limit = decision["approval_limit"]
        if decision["payout"] > limit and sign_off is None:
            raise HTTPException(
                409, f"A payout over ${limit:,.2f} waits for a handler's sign-off"
            )
        if amount != decision["payout"]:
            raise HTTPException(
                409,
                f"The amount must be the approved payout, ${decision['payout']:,.2f}",
            )
        paid = {
            "claim_id": claim_id,
            "amount": amount,
            "signed_off_by": sign_off["handler_id"] if sign_off else None,
            "signed_off_at": sign_off["signed_off_at"] if sign_off else None,
            "paid_at": db.now(),
        }
        insert_once(conn, payments, **paid)
    settle_payment(conn, claim_id)
    return {**found, "status": "decided", "payment": paid}


@router.post("/{claim_id}/hold", operation_id="hold_payment", dependencies=keys.AGENT)
def hold_payment(claim_id: str, hold: Hold, conn: Db) -> dict[str, Any]:
    """Have an approved, unpaid claim wait for a sign-off, as the Gateway refused it."""
    found = standing(conn, claim_id)
    decision = found["decision"]
    if decision is None or decision["decision"] != "approve" or found["payment"]:
        raise HTTPException(409, f"Claim {claim_id} has no approved, unpaid payout")
    move(conn, claim_id, "in_progress", "awaiting_sign_off")
    conn.execute(
        decisions.update()
        .where(decisions.c.claim_id == claim_id)
        .values(payment_refused=hold.reason)
    )
    recorded = standing(conn, claim_id)
    conn.commit()
    return recorded


@router.post("/{claim_id}/sign-off", operation_id="sign_off")
def sign_off(
    claim_id: str,
    handler: Approver,
    background_tasks: BackgroundTasks,
    conn: Db,
) -> dict[str, Any]:
    """Record the signed-in handler's sign-off on a payout, and pay it."""
    if find_claim(conn, claim_id)["evaluation_id"] is not None:
        raise HTTPException(409, f"Claim {claim_id} is a copy for an evaluation")
    # Only a claim waiting for a sign-off moves, so a second sign-off is refused.
    move(conn, claim_id, "awaiting_sign_off", "decided")
    now = db.now()
    signed = {
        "claim_id": claim_id,
        "handler_id": handler["handler_id"],
        "signed_off_at": now,
    }
    paid = {
        "claim_id": claim_id,
        "amount": standing(conn, claim_id)["decision"]["payout"],
        "signed_off_by": handler["handler_id"],
        "signed_off_at": now,
        "paid_at": now,
    }
    insert_once(conn, sign_offs, **signed)
    insert_once(conn, payments, **paid)
    conn.commit()
    # The agent closes its paused work without paying; if it's away, nothing waits.
    background_tasks.add_task(agent_service.resume, claim_id)
    return {
        "claim_id": claim_id,
        "status": "decided",
        "sign_off": signed,
        "payment": paid,
    }


@router.post("/{claim_id}/fail", operation_id="fail_claim", dependencies=keys.AGENT)
def fail_claim(claim_id: str, failure: Failure, conn: Db) -> dict[str, str]:
    """Count a failed attempt: back to the queue, or to a handler the second time."""
    status = fail(conn, claim_id, failure.reason)
    conn.commit()
    return {"claim_id": claim_id, "status": status}
