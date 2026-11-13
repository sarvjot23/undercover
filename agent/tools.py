"""The claim agent's tools. Each one is a thin layer over an operation of the app or
the context layer, on the claim's route, and fills in what the agent already knows:
the claim, its policy and its customer. So the model acts only on its own claim."""

from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import BaseTool, tool
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from agent import memory
from agent.direct import APP, CONTEXT
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
    # The customer's memory, or None when memory is off or in an evaluation.
    memory: BaseStore | None


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
        """Record a decision with its payout, reasons and policy section.

        An approval's payout must equal the latest calculate_payout for this claim.
        """
        return answer(
            claim,
            APP,
            "record_decision",
            claim_id=claim.claim_id,
            decision=decision,
            payout=payout,
            reasons=reasons,
            policy_section=policy_section,
            decided_by=maker(claim),
        )

    return [get_claim, get_policy, get_claim_history, calculate_payout, record_decision]


def context_tools(claim: ClaimContext) -> list[BaseTool]:
    """The context layer's lookups for the model, on the claim's route."""

    @tool
    def lookup_term(term: str) -> str:
        """Look up a term the policy wording defines, with the sections it is from."""
        return answer(claim, CONTEXT, "lookup_term", term=term)

    @tool
    def describe_fields(record: Literal["claim", "policy", "previous_claim"]) -> str:
        """Describe what each field means in a claim, a policy or a previous claim."""
        return answer(claim, CONTEXT, "describe_fields", record=record)

    @tool
    def get_plan(plan: Literal["economy", "premium", "first"]) -> str:
        """Get a plan's limits, waiting periods and deductible, and the add-ons."""
        return answer(claim, CONTEXT, "get_plan", plan=plan)

    @tool
    def get_claim_rules() -> str:
        """Get the rules claims operations applies to every claim, with numbers."""
        return answer(claim, CONTEXT, "get_claim_rules")

    @tool
    def search_reference_data(query: str) -> str:
        """Find outside facts, such as storms, strikes and prices, with every word."""
        return answer(claim, CONTEXT, "search_reference_data", query=query)

    @tool
    def search_documents(query: str) -> str:
        """Find the sections of the wording and the manual that mention every word."""
        return answer(claim, CONTEXT, "search_documents", query=query)

    @tool
    def read_section(document: Document, number: int) -> str:
        """Read one numbered section of the policy wording or the claims manual."""
        return answer(claim, CONTEXT, "read_section", document=document, number=number)

    return [
        lookup_term,
        describe_fields,
        get_plan,
        get_claim_rules,
        search_reference_data,
        search_documents,
        read_section,
    ]


def memory_tools(claim: ClaimContext) -> list[BaseTool]:
    """The search of the customer's memory, when the claim has one."""
    store = claim.memory
    if store is None:
        return []

    @tool
    def search_memory(query: str) -> str:
        """Search what we remember about this claim's customer from their earlier
        claims. Our claim history still counts for repeat claims."""
        return memory.search(store, claim.customer_id, claim.claim_id, query)

    return [search_memory]


def for_claim(claim: ClaimContext) -> list[BaseTool]:
    """Every tool the model has on this claim."""
    return [*app_tools(claim), *context_tools(claim), *memory_tools(claim)]
