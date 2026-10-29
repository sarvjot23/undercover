"""The claim agent's tools. Each one is a call to the backend."""

from typing import Literal

from langchain_core.tools import tool

from agent import client


@tool
def get_claim(claim_id: str) -> str:
    """Get a claim with its policy, plan limits and the customer's claim history."""
    with client.backend() as backend:
        response = backend.get(f"/api/claims/{claim_id}")
    response.raise_for_status()
    return response.text


@tool
def get_policy_wording() -> str:
    """Get the policy wording that decisions follow."""
    with client.backend() as backend:
        response = backend.get("/api/policy-wording")
    response.raise_for_status()
    return response.json()["text"]


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


TOOLS = [get_claim, get_policy_wording, record_decision, pay_claim]
