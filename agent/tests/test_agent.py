from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import claim as claim_agent
from agent import client, middleware, model, tools
from backend.api import app


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


class BrokenModel(StubModel):
    """A chat model whose provider is down."""

    def _generate(self, *args, **kwargs):
        raise RuntimeError("model down")


class FlakyModel(StubModel):
    """A chat model whose provider fails once, then answers."""

    failed: bool = False

    def _generate(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise RuntimeError("provider hiccup")
        return super()._generate(*args, **kwargs)


class Backend(TestClient):
    """The backend as the agent sees it: already running, so no startup per call."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.fixture
def requests(tmp_path, monkeypatch) -> list[str]:
    """Point the agent at the backend with a fresh database; collect its requests."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
    with TestClient(app):
        pass
    paths: list[str] = []

    def backend():
        client = Backend(app)
        client.event_hooks = {
            "request": [lambda request: paths.append(request.url.path)]
        }
        return client

    monkeypatch.setattr(client, "backend", backend)
    monkeypatch.setattr(claim_agent, "RETRY_DELAY", 0.0)
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
    return claim_agent.run("CLM-1001", "thread-1", StubModel(messages=iter(replies)))


def claim():
    with TestClient(app) as client:
        return client.get("/api/claims/CLM-1001").json()


def steps():
    with TestClient(app) as client:
        return client.get("/api/claims/CLM-1001/steps").json()


def test_approval_under_the_limit_is_paid(requests):
    answer = run(
        call("get_claim", claim_id="CLM-1001"),
        call("list_sections", document="policy_wording"),
        decision("approve", 420.0),
        call("pay_claim", claim_id="CLM-1001", amount=420.0),
        AIMessage(content="Approved, paying $420.00."),
    )
    assert answer == "CLM-1001: approve $420.00"
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
    assert len(steps()[1]["text"]) <= len("get_claim: ") + middleware.STEP_LENGTH


def broken():
    return claim_agent.run("CLM-1001", "thread-1", BrokenModel(messages=iter([])))


def test_failed_run_goes_back_to_waiting(requests):
    assert broken() == (
        "CLM-1001: failed (The agent's run failed: model down), back in the queue"
    )
    assert claim()["status"] == "waiting"
    assert claim()["attempts"] == 1
    assert steps()[-1] == {**steps()[-1], "kind": "error"}
    assert "model down" in steps()[-1]["text"]


def test_a_second_failure_leaves_the_claim_for_a_handler(requests):
    broken()
    assert broken().endswith("left for a handler")
    assert claim()["status"] == "needs_handler"
    assert claim()["attempts"] == 2


def test_a_provider_error_is_retried(requests):
    replies = iter([decision("refer", 0), AIMessage(content="Referred.")])
    answer = claim_agent.run("CLM-1001", "thread-1", FlakyModel(messages=replies))
    assert answer == "CLM-1001: refer $0.00"
    assert claim()["status"] == "decided"
    assert claim()["attempts"] == 0


def test_a_claim_stops_after_thirty_model_calls(requests):
    looping = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "get_claim", "args": {"claim_id": "CLM-1001"}, "id": f"c{i}"}
            ],
        )
        for i in range(31)
    ]
    answer = run(*looping)
    assert "failed" in answer
    assert claim()["status"] == "waiting"
    assert len([s for s in steps() if s["kind"] == "tool_call"]) == 30


def test_a_claim_that_is_not_waiting_is_not_started(requests):
    run(decision("refer", 0), AIMessage(content="Referred."))
    assert run().startswith("CLM-1001: not started, Refused (409)")


def test_run_without_a_decision_goes_back_to_waiting(requests):
    run(AIMessage(content="I am not sure."))
    assert claim()["status"] == "waiting"
    assert steps()[-1]["text"] == "The agent finished without recording a decision"


def test_agent_reaches_only_the_backend_api(requests):
    run(
        call("get_claim", claim_id="CLM-1001"),
        call("list_sections", document="policy_wording"),
        decision("refer", 0),
        AIMessage(content="Referred."),
    )
    assert "/api/instructions" in requests
    assert "/api/documents/policy_wording/sections" in requests
    assert all(path.startswith("/api/") for path in requests)


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert model.model().model_name == "deepseek/deepseek-v4.1-flash"
    assert model.model().reasoning_effort == "low"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert model.model().model_name == "openrouter/free"


def test_backend_url():
    assert str(client.backend().base_url) == "http://localhost:8000"


def test_reads_the_manual_a_section_at_a_time(requests):
    run(
        call("list_sections", document="claims_manual"),
        call("read_section", document="claims_manual", number=7),
        decision("approve", 243.0),
        AIMessage(content="Approved."),
    )
    kinds = [step["kind"] for step in steps()]
    assert kinds[:4] == ["tool_call", "tool_result", "tool_call", "read"]
    assert steps()[3]["text"] == "Claims manual · 7. Interpretation notes"
    assert "/api/documents/claims_manual/sections/7" in requests


def test_a_missing_section_is_a_refusal_not_a_read(requests):
    run(
        call("read_section", document="claims_manual", number=99),
        decision("refer", 0),
        AIMessage(content="Referred."),
    )
    assert steps()[1]["kind"] == "tool_result"
    assert "Refused (404)" in steps()[1]["text"]


def test_no_tool_hands_over_a_whole_document(requests):
    names = {t.name for t in tools.TOOLS}
    assert "get_policy_wording" not in names
    whole = Path("data/claims_manual.md").read_text(encoding="utf-8")
    section = tools.read_section.invoke({"document": "claims_manual", "number": 7})
    assert len(section) < len(whole) / 2
    listing = tools.list_sections.invoke({"document": "policy_wording"})
    assert listing.splitlines()[0] == "Policy wording"
    assert len(listing.splitlines()) == 13


def test_search_finds_the_sections_that_mention_a_word(requests):
    found = tools.search_documents.invoke({"query": "giraffes"})
    assert found.startswith("Claims manual · 7. Interpretation notes")
    assert "Nothing" in tools.search_documents.invoke({"query": "zeppelin"})
