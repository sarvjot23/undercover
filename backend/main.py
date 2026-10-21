"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException

from backend import db

INSTRUCTIONS = Path(__file__).parent / "instructions.md"

Db = Annotated[sqlite3.Connection, Depends(db.get_db)]


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


def decision_of(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any] | None:
    """Return the decision on a claim, if there is one."""
    row = conn.execute(
        "SELECT * FROM decisions WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    return dict(row) if row else None


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
