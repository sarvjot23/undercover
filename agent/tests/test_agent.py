import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent import claim as claim_agent
from agent import client, graph, tools, tracing
from agent.tests.stubs import BrokenModel, FlakyModel, StubModel, call
from backend.api import app
from backend.tests.signing import as_agent


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
    with TestClient(app, headers=as_agent()) as client:
        return client.get("/api/claims/CLM-1001").json()


def steps():
    """The claim agent's steps, after the security check's, which always comes first."""
    with TestClient(app, headers=as_agent()) as client:
        found = client.get("/api/claims/CLM-1001/steps").json()
    assert found[0]["kind"] == "check"
    return found[1:]


def test_approval_under_the_limit_is_paid(requests):
    answer = run(
        call("get_claim", claim_id="CLM-1001"),
        call("list_sections", document="policy_wording"),
        decision("approve", 420.0),
    )
    assert answer == "CLM-1001: approve $420.00"
    assert claim()["status"] == "decided"
    assert claim()["payment"]["amount"] == 420.0


def test_decline(requests):
    run(decision("decline", 0), AIMessage(content="Declined."))
    assert claim()["status"] == "decided"
    assert claim()["decision"]["decision"] == "decline"
    assert claim()["payment"] is None


def test_the_model_has_no_pay_tool():
    assert "pay_claim" not in {t.name for t in tools.TOOLS}


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
    assert len(steps()[1]["text"]) <= len("get_claim: ") + graph.STEP_LENGTH


def broken():
    thread = f"thread-{uuid.uuid4().hex}"
    return claim_agent.run("CLM-1001", thread, BrokenModel(messages=iter([])))


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
    looping = [call("get_claim", claim_id="CLM-1001") for _ in range(31)]
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
    assert "/api/configuration/current" in requests
    assert "/api/documents/policy_wording/sections" in requests
    assert all(path.startswith("/api/") for path in requests)


def test_backend_url():
    assert str(client.backend().base_url) == "http://127.0.0.1:8000"


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


def test_the_payout_tool_goes_through_the_backend(requests):
    run(
        call(
            "calculate_payout",
            claim_id="CLM-1001",
            benefit="baggage",
            lines=[
                {
                    "description": "Suit",
                    "amount": 480,
                    "quantity": 1,
                    "kind": "item",
                    "nights": 0,
                    "hours": 0,
                }
            ],
            paid_by_others=0,
        ),
        decision("refer", 0),
        AIMessage(content="Referred."),
    )
    assert "/api/claims/CLM-1001/payout" in requests
    result = next(
        s["text"] for s in steps() if s["text"].startswith("calculate_payout:")
    )
    assert '"payout":250.0' in result


def test_a_claim_is_a_langfuse_session_named_by_its_thread(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(tracing, "CallbackHandler", lambda: "handler")
    config = tracing.config("CLM-1001-ab12cd34", 10, None)
    assert config.get("metadata") == {"langfuse_session_id": "CLM-1001-ab12cd34"}
    assert config.get("callbacks") == ["handler"]


def test_no_tracing_without_the_keys():
    assert tracing.config("thread-1", 10, None).get("callbacks") == []
    tracing.flush()


def test_importing_the_product_leaves_dotenv_alone():
    code = "import os, agent.claim, backend.api; print('DATABASE_URL' in os.environ)"
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    found = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert found.stdout.strip() == "False"
