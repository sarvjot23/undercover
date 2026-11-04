from typing import Any

import pytest

from backend.payout import Line, work_out_payout

LIMIT = 800.0


def line(amount, kind: Any = "item", quantity=1, nights=0, hours=0):
    return Line(
        description=kind,
        amount=amount,
        quantity=quantity,
        kind=kind,
        nights=nights,
        hours=hours,
    )


def policy(plan="premium", add_ons=(), travelers=1, trip_cost=9000.0):
    return {
        "plan": plan,
        "add_ons": list(add_ons),
        "travelers": ["Traveler"] * travelers,
        "trip": {"trip_cost": trip_cost},
    }


def payout(lines, benefit: Any = "emergency_medical", paid=0.0, **settings):
    return work_out_payout(policy(**settings), benefit, lines, paid, LIMIT)["payout"]


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([line(480)], 300),
        ([line(340, quantity=4)], 340),
        ([line(520, "electronics")], 300),
    ],
)
def test_per_item_limits(lines, expected):
    assert payout(lines, "trip_cancellation") == expected


def test_electronics_plus_raises_the_limit():
    plain = payout([line(5000, "electronics")], "trip_cancellation")
    added = payout(
        [line(5000, "electronics")], "trip_cancellation", add_ons=["electronics_plus"]
    )
    assert added > plain


def test_cash_is_limited_in_all():
    assert payout([line(80, "cash"), line(80, "cash")], "trip_cancellation") == 100


def test_hotel_is_limited_by_rooms_and_nights():
    hotel = line(2000, "hotel", nights=2)
    assert payout([hotel], "trip_cancellation", travelers=3) == 1400


def test_meals_without_receipts_by_traveler_and_day():
    meals = line(500, "meals_without_receipts", hours=30)
    assert payout([meals], "trip_cancellation", travelers=2) == 140


def test_what_others_paid_and_the_deductible():
    assert payout([line(1000, "expense")], "emergency_medical", paid=350) == 600


def test_the_deductible_applies_only_to_its_benefits():
    assert payout([line(100, "expense")], "trip_delay") == 100


def test_the_benefit_maximum():
    assert payout([line(5000, "expense")], "trip_delay") == 800


def test_cancellation_stops_at_the_trip_cost():
    assert payout([line(4000, "expense")], "trip_cancellation", trip_cost=1000) == 1000


def test_nothing_left_to_pay():
    assert payout([line(100, "expense")], "trip_delay", paid=300) == 0


def test_the_calculation_is_shown():
    found = work_out_payout(policy(), "baggage", [line(480)], 0, LIMIT)
    assert [entry["amount"] for entry in found["calculation"]] == [300, -50]


@pytest.mark.parametrize(("amount", "expected"), [(800.0, False), (800.01, True)])
def test_the_sign_off_follows_our_settings(amount, expected):
    found = work_out_payout(
        policy(), "trip_cancellation", [line(amount, "expense")], 0, LIMIT
    )
    assert found["payout"] == amount
    assert found["needs_sign_off"] is expected


def test_the_operation_uses_the_claims_policy(client):
    response = client.post(
        "/api/claims/CLM-1001/payout",
        json={
            "benefit": "baggage",
            "lines": [line(480).model_dump()],
            "paid_by_others": 0,
        },
    )
    assert response.json()["payout"] == 250


def test_the_operation_has_no_optional_inputs(client):
    spec = client.get("/openapi.json").json()
    operation = spec["paths"]["/api/claims/{claim_id}/payout"]["post"]
    assert operation["operationId"] == "calculate_payout"
    schemas = spec["components"]["schemas"]
    assert set(schemas["PayoutRequest"]["required"]) == {
        "benefit",
        "lines",
        "paid_by_others",
    }
    assert set(schemas["Line"]["required"]) == set(schemas["Line"]["properties"])


def test_an_unknown_claim_has_no_payout(client):
    response = client.post(
        "/api/claims/CLM-9999/payout",
        json={"benefit": "baggage", "lines": [], "paid_by_others": 0},
    )
    assert response.status_code == 404
