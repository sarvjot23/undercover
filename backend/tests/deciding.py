"""Record decisions in tests as the agent does: with its maker, and for an approval
a matching calculation on file for the claim's current attempt."""

from sqlalchemy import select

from backend import db

MAKER = "UnderCover Agent, version 1"


def calculate(claim_id, payout):
    """Put a calculation that comes to this payout on file, as calculate_payout does."""
    with db.engine().begin() as conn:
        attempt = conn.execute(
            select(db.claims.c.attempts).where(db.claims.c.claim_id == claim_id)
        ).scalar_one()
        key = {"claim_id": claim_id, "attempt": attempt}
        conn.execute(
            db.calculations.delete().where(
                db.calculations.c.claim_id == claim_id,
                db.calculations.c.attempt == attempt,
            )
        )
        conn.execute(
            db.calculations.insert().values(
                **key,
                calculation={
                    "lines": [{"step": "Covered costs", "amount": payout}],
                    "payout": round(payout, 2),
                },
            )
        )


FIELDS = {
    "reasons": "The wording settles it. The documents support it.",
    "policy_section": "3. Trip Delay",
    "decided_by": MAKER,
}


def record(client, claim_id, decision, payout, **fields):
    """Record a decision on a claim in progress; fields replace the defaults."""
    if decision == "approve" and payout > 0:
        calculate(claim_id, payout)
    return client.post(
        f"/api/claims/{claim_id}/decision",
        json={"decision": decision, "payout": payout, **FIELDS, **fields},
    )


def decide(client, claim_id, decision, payout, thread_id="t", **fields):
    """Start a waiting claim and record a decision on it."""
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": thread_id})
    return record(client, claim_id, decision, payout, **fields)
