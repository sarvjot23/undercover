import boto3
import httpx
import pytest
from fastapi.testclient import TestClient

from agent import claim as claim_agent
from agent import gateway, routes, tools
from agent.direct import DEFAULT_CONTEXT, Direct
from agent.tests import stubs
from agent.tests.serving import serving
from agent.tests.standin_gateway import gateway as standin
from agent.tests.stubs import call, script
from backend.api import app
from backend.tests.signing import as_agent, as_handler

CLAIM = "CLM-1001"


def api():
    return TestClient(app, headers=as_agent())


def context_for(route, claim_id=CLAIM):
    return tools.ClaimContext(
        claim_id=claim_id,
        policy_id="POL-2001",
        customer_id="CUS-3001",
        version=1,
        kind=None,
        route=route,
        memory=None,
    )


@pytest.fixture
def unsigned(monkeypatch):
    """The Gateway route with no AWS credentials: the stand-in doesn't check them."""
    monkeypatch.setattr(gateway, "SigV4Auth", lambda session: None)


@pytest.fixture
def standin_url(requests, unsigned):
    """A stand-in Gateway that forbids nothing, and its address."""
    with serving(standin(lambda name, arguments: False)) as url:
        yield f"{url}/mcp"


def by_name(found):
    return {t.name: t for t in found}


def test_both_routes_give_the_model_the_same_tools(unsigned):
    direct = by_name(tools.for_claim(context_for(Direct(DEFAULT_CONTEXT))))
    through = by_name(tools.for_claim(context_for(gateway.Gateway("http://gw/mcp"))))
    assert direct.keys() == through.keys()
    for name, found in direct.items():
        assert found.args == through[name].args
        assert not {"claim_id", "policy_id", "customer_id"} & found.args.keys()


def test_get_claim_gives_the_same_text_on_both_routes(standin_url):
    direct = tools.app_tools(context_for(Direct(DEFAULT_CONTEXT)))[0].invoke({})
    through = tools.app_tools(context_for(gateway.Gateway(standin_url)))[0].invoke({})
    assert direct == through
    assert direct == api().get(f"/api/claims/{CLAIM}").text


def test_the_context_layer_answers_the_same_through_the_gateway(standin_url):
    claim = context_for(gateway.Gateway(standin_url))
    through = {t.name: t for t in tools.context_tools(claim)}
    direct = {t.name: t for t in tools.context_tools(context_for(routes.choose()))}
    question = {"term": "Unattended"}
    assert through["lookup_term"].invoke(question) == (
        direct["lookup_term"].invoke(question)
    )
    assert "glossary.yaml" in through["lookup_term"].invoke(question)


def test_a_refusal_by_the_app_on_each_route(standin_url):
    for route in (Direct(DEFAULT_CONTEXT), gateway.Gateway(standin_url)):
        found = tools.app_tools(context_for(route, "CLM-9999"))[0].invoke({})
        assert found == "Refused by the app: (404) No claim CLM-9999"


def steps():
    found = api().get(f"/api/claims/{CLAIM}/steps").json()
    return [step["text"] for step in found if step["kind"] != "check"]


def on_gateway(monkeypatch, url):
    monkeypatch.setenv("UNDERCOVER_GATEWAY_URL", url)


def test_a_tool_the_gateway_refuses_is_a_refusal_and_work_goes_on(
    requests, unsigned, monkeypatch
):
    forbidden = standin(lambda name, arguments: name.endswith("calculate_payout"))
    with serving(forbidden) as url:
        on_gateway(monkeypatch, f"{url}/mcp")
        report = claim_agent.run(
            CLAIM,
            "thread-1",
            script(
                call("calculate_payout", benefit="baggage", lines=[], paid_by_others=0),
                call(
                    "record_decision",
                    decision="refer",
                    payout=0,
                    reasons="The payout couldn't be worked out. A handler decides.",
                    policy_section="Claims manual 2.",
                ),
            ),
        )
    assert report == f"{CLAIM}: refer $0.00"
    refusal = next(text for text in steps() if text.startswith("calculate_payout:"))
    assert refusal.startswith("calculate_payout: Refused by the Gateway:")
    assert "Tool Execution Denied" in refusal
    assert "undercover-app___record_decision" in forbidden.state.calls


def test_a_payment_the_gateway_refuses_waits_for_a_sign_off(
    requests, unsigned, monkeypatch
):
    forbidden = standin(lambda name, arguments: name.endswith("pay_claim"))
    with serving(forbidden) as url:
        on_gateway(monkeypatch, f"{url}/mcp")
        report = claim_agent.run(
            CLAIM,
            "thread-1",
            script(*stubs.decide("approve", 420.0, CLAIM)),
        )
        assert report == f"{CLAIM}: approve $420.00, waiting for a handler's sign-off"
        found = api().get(f"/api/claims/{CLAIM}").json()
        assert found["status"] == "awaiting_sign_off"
        assert found["payment"] is None
        assert "Tool Execution Denied" in found["decision"]["payment_refused"]
        assert any("Refused by the Gateway" in text for text in steps())
        signed = api().post(f"/api/claims/{CLAIM}/sign-off", headers=as_handler())
        assert signed.json()["payment"]["amount"] == 420.0
        assert claim_agent.carry_on(CLAIM).endswith("approve $420.00")
    assert api().get(f"/api/claims/{CLAIM}").json()["status"] == "decided"


def test_the_route_is_read_when_a_graph_is_built(unsigned, monkeypatch):
    monkeypatch.delenv("UNDERCOVER_GATEWAY_URL", raising=False)
    monkeypatch.delenv("UNDERCOVER_CONTEXT", raising=False)
    direct = routes.choose()
    assert isinstance(direct, Direct)
    assert direct.context_url == DEFAULT_CONTEXT
    monkeypatch.setenv("UNDERCOVER_CONTEXT", "http://context.test/mcp")
    overridden = routes.choose()
    assert isinstance(overridden, Direct)
    assert overridden.context_url == "http://context.test/mcp"
    monkeypatch.setenv("UNDERCOVER_GATEWAY_URL", "http://gw.test/mcp")
    through = routes.choose()
    assert isinstance(through, gateway.Gateway)
    assert (
        through.tool_name("undercover-app", "get_claim") == "undercover-app___get_claim"
    )


def test_the_gateway_route_signs_for_bedrock_agentcore():
    session = boto3.Session(
        aws_access_key_id="AKIDEXAMPLE",
        aws_secret_access_key="secret",  # noqa: S106
        region_name="us-east-1",
    )
    request = httpx.Request("POST", "https://gw.test/mcp", json={"jsonrpc": "2.0"})
    signed = next(gateway.SigV4Auth(session).auth_flow(request))
    authorization = signed.headers["Authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256")
    assert "/us-east-1/bedrock-agentcore/aws4_request" in authorization
    assert "X-Amz-Date" in signed.headers
