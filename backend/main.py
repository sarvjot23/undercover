"""The UnderCover backend."""

import json
import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import main as agent
from backend import db

INSTRUCTIONS = Path(__file__).parent / "instructions.md"
APPROVAL_LIMIT = 800.0

Db = Annotated[sqlite3.Connection, Depends(db.get_db)]


class Decision(BaseModel):
    """The agent's decision on a claim."""

    decision: Literal["approve", "decline", "refer"]
    payout: float = Field(ge=0)
    reasons: str = Field(min_length=1)
    policy_section: str = Field(min_length=1)


class Payment(BaseModel):
    """A payment of a claim's approved payout."""

    amount: float


class SignOff(BaseModel):
    """A handler's sign-off on a payout over the approval limit."""

    handler_id: str


class Step(BaseModel):
    """One step of the agent's work on a claim."""

    kind: Literal["tool_call", "tool_result", "answer", "error"]
    text: str


class Failure(BaseModel):
    """Why the agent's run on a claim failed."""

    reason: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create and seed the database when the backend starts."""
    db.init()
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)


LOOKUPS = {
    "policy": "SELECT body FROM policies WHERE policy_id = ?",
    "customer": "SELECT body FROM customers WHERE customer_id = ?",
    "plan": "SELECT body FROM plans WHERE plan = ?",
}


def record(conn: sqlite3.Connection, kind: str, key: str) -> Any:
    """Return one stored policy, customer or plan."""
    return json.loads(conn.execute(LOOKUPS[kind], (key,)).fetchone()["body"])


def find_claim(conn: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    """Return a claim's row, or raise 404."""
    row = conn.execute(
        "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No claim {claim_id}")
    return row


def agent_working(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Whether the agent is still at work: in progress, or not yet given its answer."""
    last = conn.execute(
        "SELECT kind FROM steps WHERE claim_id = ? ORDER BY step_id DESC LIMIT 1",
        (row["claim_id"],),
    ).fetchone()
    return row["status"] == "in_progress" or (
        last is not None and last["kind"] in ("tool_call", "tool_result")
    )


def decision_of(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any] | None:
    """Return the decision on a claim, if there is one."""
    row = conn.execute(
        "SELECT * FROM decisions WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    return dict(row) if row else None


def move(conn: sqlite3.Connection, claim_id: str, before: str, after: str) -> None:
    """Move a claim from one state to another, or raise 409."""
    find_claim(conn, claim_id)
    cursor = conn.execute(
        "UPDATE claims SET status = ? WHERE claim_id = ? AND status = ?",
        (after, claim_id, before),
    )
    if cursor.rowcount == 0:
        raise HTTPException(409, f"Claim {claim_id} is not {before}")


def add(conn: sqlite3.Connection, claim_id: str, kind: str, text: str) -> None:
    """Record one step of the agent's work."""
    conn.execute(
        "INSERT INTO steps (claim_id, kind, text, at) VALUES (?, ?, ?, ?)",
        (claim_id, kind, text, db.now()),
    )


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
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


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
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


@app.get("/api/policy-wording", operation_id="get_policy_wording")
def get_policy_wording() -> dict[str, str]:
    """Get the policy wording that decisions follow."""
    return {"text": (db.DATA / "policy_wording.md").read_text(encoding="utf-8")}


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions() -> dict[str, str]:
    """Get the UnderCover Agent's instructions."""
    return {"text": INSTRUCTIONS.read_text(encoding="utf-8")}


@app.get("/api/handlers", operation_id="list_handlers")
def list_handlers(conn: Db) -> list[dict[str, Any]]:
    """List the claims handlers."""
    return [
        json.loads(row["body"]) for row in conn.execute("SELECT body FROM handlers")
    ]


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: Db) -> list[dict[str, Any]]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(conn, claim_id)
    rows = conn.execute(
        "SELECT * FROM steps WHERE claim_id = ? ORDER BY step_id", (claim_id,)
    )
    return [dict(row) for row in rows]


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, conn: Db) -> dict[str, str]:
    """Mark a waiting claim as in progress."""
    with conn:
        move(conn, claim_id, "waiting", "in_progress")
    return {"claim_id": claim_id, "status": "in_progress"}


@app.post("/api/claims/{claim_id}/steps", operation_id="add_step")
def add_step(claim_id: str, step: Step, conn: Db) -> dict[str, str]:
    """Record one step of the agent's work on a claim."""
    find_claim(conn, claim_id)
    with conn:
        add(conn, claim_id, step.kind, step.text)
    return {"claim_id": claim_id, "kind": step.kind}


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
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


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
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


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off")
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


@app.post("/api/claims/{claim_id}/fail", operation_id="fail_claim")
def fail_claim(claim_id: str, failure: Failure, conn: Db) -> dict[str, str]:
    """Send a claim back to waiting after the agent's run failed."""
    with conn:
        move(conn, claim_id, "in_progress", "waiting")
        add(conn, claim_id, "error", failure.reason)
    return {"claim_id": claim_id, "status": "waiting"}


@app.post("/api/claims/{claim_id}/run", operation_id="run_claim")
def run_claim(
    claim_id: str, background_tasks: BackgroundTasks, conn: Db
) -> dict[str, str]:
    """Start the UnderCover Agent on a waiting claim."""
    if find_claim(conn, claim_id)["status"] != "waiting":
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    thread_id = f"{claim_id}-{uuid.uuid4().hex[:8]}"
    background_tasks.add_task(agent.run, claim_id, thread_id)
    return {"claim_id": claim_id, "thread_id": thread_id}
