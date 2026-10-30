"""The claim agent's tools. Each one is a call to the backend."""

from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent import client

Document = Literal["policy_wording", "claims_manual"]
Benefit = Literal[
    "trip_cancellation",
    "trip_interruption",
    "trip_delay",
    "baggage_delay",
    "baggage",
    "passport",
    "emergency_medical",
]


class Line(BaseModel):
    """One covered item or expense on a claim."""

    description: str = Field(description="What the item or expense is")
    amount: float = Field(
        description="The total claimed for the line in US dollars, before any limits. "
        "For several items, the total for all of them"
    )
    quantity: int = Field(
        ge=1,
        description="How many separate items the line holds, such as 3 for three "
        "shirts. A pair or a set is one item",
    )
    kind: Literal[
        "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
    ] = Field(
        description="item: a belonging, or a pair or set that counts as one item. "
        "electronics: only a phone, tablet, laptop, camera or its lens, e-reader or "
        "smartwatch; any other device is an item. "
        "cash: cash that was lost or stolen. "
        "expense: any other cost with a receipt, such as a medical bill, a meal, a "
        "taxi, a fee or a prepaid trip cost. "
        "hotel: a hotel during a trip delay. "
        "meals_without_receipts: meals during a trip delay with no receipts."
    )
    nights: int = Field(description="For a hotel, the number of nights; otherwise 0")
    hours: float = Field(
        description="For meals without receipts, the length of the delay in hours; "
        "otherwise 0"
    )


@tool
def get_claim(claim_id: str) -> str:
    """Get a claim with its policy, plan limits and the customer's claim history."""
    with client.backend() as backend:
        response = backend.get(f"/api/claims/{claim_id}")
    return client.reply(response)


@tool
def list_sections(document: Document) -> str:
    """List the numbered sections of the policy wording or the claims manual."""
    with client.backend() as backend:
        response = backend.get(f"/api/documents/{document}/sections")
    if not response.is_success:
        return client.reply(response)
    found = response.json()
    titles = [f"{s['number']}. {s['title']}" for s in found["sections"]]
    return "\n".join([found["name"], *titles])


@tool
def read_section(document: Document, number: int) -> str:
    """Read one numbered section of the policy wording or the claims manual."""
    with client.backend() as backend:
        response = backend.get(f"/api/documents/{document}/sections/{number}")
    if not response.is_success:
        return client.reply(response)
    section = response.json()
    heading = f"{section['name']} · {section['number']}. {section['title']}"
    return f"{heading}\n\n{section['text']}"


@tool
def search_documents(query: str) -> str:
    """Find the sections of the wording and the manual that mention every word."""
    with client.backend() as backend:
        response = backend.get(f"/api/documents/search/{query}")
    found = response.json()
    if not found:
        return f"Nothing in the wording or the manual mentions {query!r}."
    return "\n\n".join(
        f"{f['name']} · {f['number']}. {f['title']}\n" + "\n".join(f["lines"][:5])
        for f in found
    )


@tool
def calculate_payout(
    claim_id: str, benefit: Benefit, lines: list[Line], paid_by_others: float
) -> str:
    """Work out the payout on an approved claim with UnderCover's payout rules.

    List each covered line, leaving out excluded ones. paid_by_others is anything a
    carrier, hotel or other party has paid or refunded for the same loss, or 0.
    """
    with client.backend() as backend:
        response = backend.post(
            f"/api/claims/{claim_id}/payout",
            json={
                "benefit": benefit,
                "lines": [line.model_dump() for line in lines],
                "paid_by_others": paid_by_others,
            },
        )
    return client.reply(response)


@tool
def record_decision(
    claim_id: str,
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    reasons: str,
    policy_section: str,
) -> str:
    """Record a decision with its payout, reasons and policy section."""
    with client.backend() as backend:
        response = backend.post(
            f"/api/claims/{claim_id}/decision",
            json={
                "decision": decision,
                "payout": payout,
                "reasons": reasons,
                "policy_section": policy_section,
            },
        )
    return client.reply(response)


@tool
def pay_claim(claim_id: str, amount: float) -> str:
    """Pay an approved claim's payout."""
    with client.backend() as backend:
        response = backend.post(
            f"/api/claims/{claim_id}/payment", json={"amount": amount}
        )
    return client.reply(response)


TOOLS = [
    get_claim,
    list_sections,
    read_section,
    search_documents,
    calculate_payout,
    record_decision,
    pay_claim,
]
