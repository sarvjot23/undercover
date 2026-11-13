"""The payout rules for an approved claim.

From section 10 of the policy wording, the plans as seeding loads them from
context/plans.yaml, and sections 6, 7 and 10 of the claims manual.
"""

from math import ceil, inf
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

CASH_LIMIT = 100.0
HOTEL_NIGHT_LIMIT = 350.0
MEALS_PER_TRAVELER_PER_DAY = 35.0

Benefit = Literal[
    "trip_cancellation",
    "trip_interruption",
    "trip_delay",
    "baggage_delay",
    "baggage",
    "passport",
    "emergency_medical",
]

BENEFIT_MAXIMUM = {
    "trip_cancellation": "trip_cancellation_max",
    "trip_interruption": "trip_cancellation_max",
    "trip_delay": "trip_delay_max",
    "baggage_delay": "baggage_delay_max",
    "baggage": "baggage_max",
    "passport": "passport_max",
    "emergency_medical": "emergency_medical_max",
}


class Line(BaseModel):
    """One covered item or expense on a claim."""

    description: str
    amount: float
    quantity: int = Field(ge=1)
    kind: Literal[
        "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
    ]
    nights: int
    hours: float


class CalculationStep(TypedDict):
    """One line of the calculation."""

    step: str
    amount: float


class Payout(TypedDict):
    """The payout on a claim and the calculation behind it."""

    calculation: list[CalculationStep]
    payout: float
    needs_sign_off: bool


def step(description: str, amount: float) -> CalculationStep:
    """Make one line of the calculation, rounded to the cent."""
    return {"step": description, "amount": round(amount, 2)}


def electronics_plus_limit(plan: dict[str, Any]) -> float:
    """The per-item limit for electronics with the Electronics Plus add-on."""
    return next(
        add_on["electronics_per_item_limit"]
        for add_on in plan["add_ons"]
        if add_on["add_on"] == "electronics_plus"
    )


def limit_for(line: Line, policy: dict[str, Any]) -> float:
    """Return the most we pay for one line, or infinity if it has no limit."""
    plan = policy["plan_rules"]
    travelers = len(policy["travelers"])
    match line.kind:
        case "item":
            return plan["per_item_limit"] * line.quantity
        case "electronics":
            electronics_plus = "electronics_plus" in policy["add_ons"]
            per_item = (
                electronics_plus_limit(plan)
                if electronics_plus
                else plan["per_item_limit"]
            )
            return per_item * line.quantity
        case "hotel":
            return HOTEL_NIGHT_LIMIT * ceil(travelers / 2) * line.nights
        case "meals_without_receipts":
            return MEALS_PER_TRAVELER_PER_DAY * travelers * ceil(line.hours / 24)
        case _:
            return inf


def eligible_amount(line: Line, policy: dict[str, Any]) -> CalculationStep:
    """Return the amount claimed on a line, or its limit if that is lower."""
    limit = limit_for(line, policy)
    if line.amount > limit:
        return step(f"{line.description}, limited to ${limit:,.2f}", limit)
    return step(line.description, line.amount)


def benefit_maximum(policy: dict[str, Any], benefit: Benefit) -> float:
    """Return the most the plan pays; cancellation also stops at the trip cost."""
    maximum = policy["plan_rules"][BENEFIT_MAXIMUM[benefit]]
    if benefit in ("trip_cancellation", "trip_interruption"):
        return min(maximum, policy["trip"]["trip_cost"])
    return maximum


def work_out_payout(
    policy: dict[str, Any],
    benefit: Benefit,
    lines: list[Line],
    paid_by_others: float,
    limit: float,
) -> Payout:
    """Work out the payout on an approved claim, following section 10 of the wording.

    The policy carries its plan's rules as plan_rules. It needs a sign-off when
    it's over the approval limit.
    """
    plan = policy["plan_rules"]
    calculation = [
        eligible_amount(line, policy) for line in lines if line.kind != "cash"
    ]
    cash = sum(line.amount for line in lines if line.kind == "cash")
    if cash:
        calculation.append(
            step(f"Cash, up to ${CASH_LIMIT:,.0f} in all", min(cash, CASH_LIMIT))
        )
    total = sum(entry["amount"] for entry in calculation)

    if paid_by_others:
        calculation.append(
            step("Less what others have paid or refunded", -paid_by_others)
        )
        total -= paid_by_others

    if benefit in plan["deductible_applies_to"] and total > 0:
        deductible = min(plan["deductible"], total)
        if deductible:
            calculation.append(step("Less the deductible", -deductible))
            total -= deductible

    maximum = benefit_maximum(policy, benefit)
    if total > maximum:
        calculation.append(
            step(
                f"Less the amount over the maximum of ${maximum:,.0f}", maximum - total
            )
        )
        total = maximum

    if total < 0:
        calculation.append(step("Nothing is left to pay", -total))
        total = 0.0

    payout = round(total, 2)
    return {
        "calculation": calculation,
        "payout": payout,
        "needs_sign_off": payout > limit,
    }
