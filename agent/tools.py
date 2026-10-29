"""The claim agent's tools. Each one is a call to the backend."""

from typing import Literal

from langchain_core.tools import tool

from agent import client

Document = Literal["policy_wording", "claims_manual"]


@tool
def get_claim(claim_id: str) -> str:
    """Get a claim with its policy, plan limits and the customer's claim history."""
    with client.backend() as backend:
        response = backend.get(f"/api/claims/{claim_id}")
    response.raise_for_status()
    return response.text


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
    record_decision,
    pay_claim,
]
