import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import main
from backend.main import app


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


class BrokenModel(StubModel):
    """A chat model whose provider is down."""

    def _generate(self, *args, **kwargs):
        raise RuntimeError("model down")


@pytest.fixture
def requests(tmp_path, monkeypatch) -> list[str]:
    """Point the agent at the backend with a fresh database; collect its requests."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
    paths: list[str] = []

    def backend():
        client = TestClient(app)
        client.event_hooks = {
            "request": [lambda request: paths.append(request.url.path)]
        }
        return client

    monkeypatch.setattr(main, "backend", backend)
    return paths


def call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name}])


def decision(decision, payout):
    return call(
        "record_decision",
        claim_id="CLM-1001",
        decision=decision,
        payout=payout,
        reasons="The wording settles it. The documents support it.",
        policy_section="3. Trip Delay",
    )


def run(*replies):
    return main.run("CLM-1001", "thread-1", StubModel(messages=iter(replies)))


def claim():
    with TestClient(app) as client:
        return client.get("/api/claims/CLM-1001").json()


def steps():
    with TestClient(app) as client:
        return client.get("/api/claims/CLM-1001/steps").json()


def test_approval_under_the_limit_is_paid(requests):
    answer = run(
        call("get_claim", claim_id="CLM-1001"),
        call("get_policy_wording"),
        decision("approve", 420.0),
        call("pay_claim", claim_id="CLM-1001", amount=420.0),
        AIMessage(content="Approved, paying $420.00."),
    )
    assert answer == "Approved, paying $420.00."
    assert claim()["status"] == "decided"
    assert claim()["payment"]["amount"] == 420.0


def test_decline(requests):
    run(decision("decline", 0), AIMessage(content="Declined."))
    assert claim()["status"] == "decided"
    assert claim()["decision"]["decision"] == "decline"
    assert claim()["payment"] is None


def test_payment_over_the_limit_is_refused(requests):
    run(
        decision("approve", 1200.0),
        call("pay_claim", claim_id="CLM-1001", amount=1200.0),
        AIMessage(content="Approved; the payment waits for sign-off."),
    )
    assert claim()["status"] == "awaiting_sign_off"
    assert claim()["payment"] is None
    results = [step["text"] for step in steps() if step["kind"] == "tool_result"]
    assert results[-1].startswith("pay_claim: Refused (409)")


def test_steps_are_recorded_in_order(requests):
    run(
        call("get_claim", claim_id="CLM-1001"),
        decision("refer", 0),
        AIMessage(content="Referred."),
    )
    assert [step["kind"] for step in steps()] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "answer",
    ]
    assert steps()[0]["text"] == 'get_claim {"claim_id": "CLM-1001"}'
    assert steps()[1]["text"].startswith('get_claim: {"claim_id":"CLM-1001"')
    assert len(steps()[1]["text"]) <= len("get_claim: ") + main.STEP_LENGTH


def test_failed_run_goes_back_to_waiting(requests):
    with pytest.raises(RuntimeError, match="model down"):
        main.run("CLM-1001", "thread-1", BrokenModel(messages=iter([])))
    assert claim()["status"] == "waiting"
    assert steps()[-1] == {**steps()[-1], "kind": "error"}
    assert "model down" in steps()[-1]["text"]


def test_run_without_a_decision_goes_back_to_waiting(requests):
    run(AIMessage(content="I am not sure."))
    assert claim()["status"] == "waiting"
    assert steps()[-1]["text"] == "The agent finished without recording a decision"


def test_agent_reaches_only_the_backend_api(requests):
    run(
        call("get_claim", claim_id="CLM-1001"),
        call("get_policy_wording"),
        decision("refer", 0),
        AIMessage(content="Referred."),
    )
    assert "/api/instructions" in requests
    assert "/api/policy-wording" in requests
    assert all(path.startswith("/api/") for path in requests)


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert main.model().model_name == "openai/gpt-6-luna"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"


def test_backend_url():
    assert str(main.backend().base_url) == "http://localhost:8000"
