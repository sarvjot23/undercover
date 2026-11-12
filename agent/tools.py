"""The claim agent's tools. Each one is a thin layer over an operation of the app or
the context layer, on the claim's route, and fills in what the agent already knows:
the claim, its policy and its customer. So the model acts only on its own claim."""

from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agent import client
from agent.direct import APP
from agent.mcp_bridge import Refused
from agent.routes import Route

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


@dataclass(frozen=True)
class ClaimContext:
    """What the agent knows about the claim it's working, besides the model."""

    claim_id: str
    policy_id: str
    customer_id: str
    version: int
    kind: str | None
    route: Route


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


def maker(claim: ClaimContext) -> str:
    """Who makes the decision, for the record: the agent and its version."""
    return f"UnderCover Agent, version {claim.version}"


def answer(
    claim: ClaimContext, target: str, operation: str, **arguments: object
) -> str:
    """Call an operation on the claim's route; a refusal is the model's answer."""
    try:
        return claim.route.call(target, operation, arguments)
    except Refused as refused:
        return str(refused)


def app_tools(claim: ClaimContext) -> list[BaseTool]:
    """The app's operations for the model, on its own claim, policy and customer."""

    @tool
    def get_claim() -> str:
        """Get the claim with its policy, plan limits and claim history."""
        return answer(claim, APP, "get_claim", claim_id=claim.claim_id)

    @tool
    def get_policy() -> str:
        """Get the customer's policy with its plan's limits."""
        return answer(claim, APP, "get_policy", policy_id=claim.policy_id)

    @tool
    def get_claim_history() -> str:
        """Get the customer's claim history with UnderCover."""
        return answer(claim, APP, "get_claim_history", customer_id=claim.customer_id)

    @tool
    def calculate_payout(
        benefit: Benefit, lines: list[Line], paid_by_others: float
    ) -> str:
        """Work out the payout on an approved claim with UnderCover's payout rules.

        List each covered line, leaving out excluded ones. paid_by_others is anything a
        carrier, hotel or other party has paid or refunded for the same loss, or 0.
        """
        return answer(
            claim,
            APP,
            "calculate_payout",
            claim_id=claim.claim_id,
            benefit=benefit,
            lines=[line.model_dump() for line in lines],
            paid_by_others=paid_by_others,
        )

    @tool
    def record_decision(
        decision: Literal["approve", "decline", "refer"],
        payout: float,
        reasons: str,
        policy_section: str,
    ) -> str:
        """Record a decision with its payout, reasons and policy section."""
        return answer(
            claim,
            APP,
            "record_decision",
            claim_id=claim.claim_id,
            decision=decision,
            payout=payout,
            reasons=reasons,
            policy_section=policy_section,
        )

    return [get_claim, get_policy, get_claim_history, calculate_payout, record_decision]


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


DOCUMENT_TOOLS = [list_sections, read_section, search_documents]


def for_claim(claim: ClaimContext) -> list[BaseTool]:
    """Every tool the model has on this claim."""
    return [*app_tools(claim), *DOCUMENT_TOOLS]
