"""Claims manual section 14: what a decision record must hold.

Each refusal is a 422 naming section 14 and what's missing, in a message of our own
so the agent can put it right and try again.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, select

from backend.db import calculations, documents
from backend.payout import Payout
from backend.schemas import Decision

SECTION_14 = "Claims manual section 14"


def refuse(missing: str) -> HTTPException:
    """A refusal that names section 14 and what the record is missing."""
    return HTTPException(422, f"{SECTION_14}: {missing}")


def check_request(decision: Decision) -> None:
    """The record's own checks, which come before the claim is looked at."""
    if not decision.reasons.strip():
        raise refuse("the record needs a reason in plain language")
    if not decision.policy_section.strip():
        raise refuse("the record needs the section relied on")
    if not decision.decided_by.strip():
        raise refuse("the record needs who or what made the decision")
    if decision.decision == "approve" and decision.payout <= 0:
        raise refuse("an approval pays more than $0")
    if decision.decision != "approve" and decision.payout != 0:
        raise refuse("a decline or a referral pays $0")


def store_calculation(conn: Connection, claim: RowMapping, payout: Payout) -> None:
    """Keep a claim's latest calculation for its current attempt."""
    key = {"claim_id": claim["claim_id"], "attempt": claim["attempts"]}
    calculation = {"lines": payout["calculation"], "payout": payout["payout"]}
    conn.execute(
        calculations.delete().where(
            calculations.c.claim_id == key["claim_id"],
            calculations.c.attempt == key["attempt"],
        )
    )
    conn.execute(calculations.insert().values(**key, calculation=calculation))


def calculation_for(
    conn: Connection, decision: Decision, claim_id: str, attempt: int
) -> dict[str, Any] | None:
    """The calculation an approval rests on, which its payout must equal."""
    if decision.decision != "approve":
        return None
    query = select(calculations.c.calculation).where(
        calculations.c.claim_id == claim_id, calculations.c.attempt == attempt
    )
    found = conn.execute(query).scalar_one_or_none()
    if found is None:
        raise refuse(
            "an approval needs the payout calculation for this attempt: "
            "work it out with calculate_payout first"
        )
    if round(decision.payout, 2) != found["payout"]:
        raise refuse(f"the payout must equal the calculation's ${found['payout']:,.2f}")
    return found


def manual_version(conn: Connection) -> str:
    """The version of the claims manual in force (section 13)."""
    query = select(documents.c.version).where(documents.c.document == "claims_manual")
    return conn.execute(query).scalar_one()
