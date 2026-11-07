import json

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from backend.api import app

DOCUMENT = "/api/agent/openapi.json"


def operations(document):
    return {
        operation["operationId"]: operation
        for path in document["paths"].values()
        for operation in path.values()
    }


def test_the_document_has_exactly_the_agents_eight_operations(client):
    document = client.get(DOCUMENT).json()
    assert set(operations(document)) == {
        "get_claim",
        "get_policy",
        "get_claim_history",
        "search_documents",
        "read_section",
        "calculate_payout",
        "record_decision",
        "pay_claim",
    }
    assert "servers" not in document
    assert "X-API-Key" not in json.dumps(document)
    assert "security" not in json.dumps(document)


def test_each_operation_is_described_by_its_one_line_docstring(client):
    found = operations(client.get(DOCUMENT).json())
    routes = {
        context.route.operation_id: context.route
        for context in iter_route_contexts(app.routes)
        if isinstance(context.route, APIRoute)
    }
    for name, operation in found.items():
        assert operation["description"] == routes[name].endpoint.__doc__
        assert "\n" not in operation["description"]


def test_the_payment_takes_an_amount(client):
    document = client.get(DOCUMENT).json()
    schema = document["components"]["schemas"]["Payment"]
    assert schema["required"] == ["amount"]
    assert operations(document)["pay_claim"]["requestBody"]["required"] is True


@pytest.mark.usefixtures("client")
def test_the_document_needs_the_key_or_a_handler():
    assert TestClient(app).get(DOCUMENT).status_code == 401


def test_the_policy_and_history_match_the_claim(client):
    claim = client.get("/api/claims/CLM-1001").json()
    policy = client.get(f"/api/policies/{claim['policy_id']}").json()
    assert {k: v for k, v in policy.items() if k != "plan_limits"} == claim["policy"]
    assert policy["plan_limits"] == claim["plan"]
    history = client.get(f"/api/customers/{claim['customer_id']}/claims").json()
    assert history == claim["customer"]


def test_an_unknown_policy_or_customer_is_404(client):
    assert client.get("/api/policies/POL-0000").status_code == 404
    assert client.get("/api/customers/CUS-0000/claims").status_code == 404
