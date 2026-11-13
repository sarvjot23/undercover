import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent import claim as claim_agent
from agent import client, graph, routes, tools, tracing
from agent.tests import stubs
from agent.tests.stubs import BrokenModel, FlakyModel, StubModel, call
from backend.api import app
from backend.tests.signing import as_agent


def decision(choice, payout):
    return stubs.decide(choice, payout)


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
        call("get_claim"),
        call("read_section", document="policy_wording", number=3),
        *decision("approve", 420.0),
    )
    assert answer == "CLM-1001: approve $420.00"
    assert claim()["status"] == "decided"
    assert claim()["payment"]["amount"] == 420.0
    record = claim()["decision"]
    assert record["calculation"]["payout"] == 420.0
    assert record["decided_by"] == "UnderCover Agent, version 1"
    assert record["manual_version"] == "2026.2"


def test_a_record_section_14_refuses_is_put_right_and_tried_again(requests):
    run(
        *decision("approve", 420.0)[1:],
        *decision("approve", 420.0),
        AIMessage(content="Approved."),
    )
    refusal = next(s for s in steps() if s["kind"] == "refusal")
    assert refusal["text"].startswith("record_decision: Refused by the app:")
    assert "Claims manual section 14" in refusal["text"]
    assert refusal["detail"] == {"by": "the app"}
    assert claim()["decision"]["payout"] == 420.0


def test_decline(requests):
    run(*decision("decline", 0), AIMessage(content="Declined."))
    assert claim()["status"] == "decided"
    assert claim()["decision"]["decision"] == "decline"
    assert claim()["payment"] is None


def claim_tools():
    """The model's tools on CLM-1001, on the direct route the settings give."""
    route = routes.choose()
    found = tools.ClaimContext("CLM-1001", "POL-2001", "CUS-3001", 1, None, route, None)
    return {t.name: t for t in tools.for_claim(found)}


def test_the_model_has_its_tools_and_no_pay_tool(requests):
    assert set(claim_tools()) == {
        "get_claim",
        "get_policy",
        "get_claim_history",
        "calculate_payout",
        "record_decision",
        "lookup_term",
        "describe_fields",
        "get_plan",
        "get_claim_rules",
        "search_reference_data",
        "search_documents",
        "read_section",
    }


def test_steps_are_recorded_in_order(requests):
    run(
        call("get_claim"),
        *decision("refer", 0),
        AIMessage(content="Referred."),
    )
    assert [step["kind"] for step in steps()] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "answer",
    ]
    assert steps()[0]["text"] == "get_claim {}"
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
    replies = iter([*decision("refer", 0), AIMessage(content="Referred.")])
    answer = claim_agent.run("CLM-1001", "thread-1", FlakyModel(messages=replies))
    assert answer == "CLM-1001: refer $0.00"
    assert claim()["status"] == "decided"
    assert claim()["attempts"] == 0


def test_a_claim_stops_after_thirty_model_calls(requests):
    looping = [call("get_claim") for _ in range(31)]
    answer = run(*looping)
    assert "failed" in answer
    assert claim()["status"] == "waiting"
    assert len([s for s in steps() if s["kind"] == "tool_call"]) == 30


def test_a_claim_that_is_not_waiting_is_not_started(requests):
    run(*decision("refer", 0), AIMessage(content="Referred."))
    assert run().startswith("CLM-1001: not started, Refused (409)")


def test_run_without_a_decision_goes_back_to_waiting(requests):
    run(AIMessage(content="I am not sure."))
    assert claim()["status"] == "waiting"
    assert steps()[-1]["text"] == "The agent finished without recording a decision"


def test_agent_reaches_only_the_backend_api(requests):
    run(
        call("get_claim"),
        call("search_documents", query="unattended"),
        *decision("refer", 0),
        AIMessage(content="Referred."),
    )
    assert "/api/configuration/current" in requests
    assert not any("documents" in path for path in requests)
    assert all(path.startswith("/api/") for path in requests)


def test_backend_url():
    assert str(client.backend().base_url) == "http://127.0.0.1:8000"


def test_reads_the_manual_a_section_at_a_time(requests):
    run(
        call("search_documents", query="giraffes"),
        call("read_section", document="claims_manual", number=7),
        *decision("approve", 243.0),
        AIMessage(content="Approved."),
    )
    kinds = [step["kind"] for step in steps()]
    assert kinds[:4] == ["tool_call", "lookup", "tool_call", "lookup"]
    assert steps()[3]["text"] == "Claims manual · 7. Interpretation notes"
    manual = {
        "file": "claims_manual.md",
        "system": "Claims operations",
        "owner": "Head of claims operations",
        "reviewed": "2026-09-01",
    }
    assert steps()[1]["text"] == "The documents, for “giraffes”"
    assert steps()[1]["detail"]["files"] == [manual]
    assert steps()[3]["detail"] == {
        "looked_up": "Claims manual · 7. Interpretation notes",
        "files": [manual],
    }


def test_a_missing_section_is_a_refusal_not_a_read(requests):
    run(
        call("read_section", document="claims_manual", number=99),
        *decision("refer", 0),
        AIMessage(content="Referred."),
    )
    assert steps()[1]["kind"] == "refusal"
    assert steps()[1]["detail"] == {"by": "the context layer"}
    assert steps()[1]["text"] == (
        "read_section: Refused by the context layer: "
        "Error executing tool read_section: No section 99 in the claims manual"
    )


def test_no_tool_hands_over_a_whole_document(requests):
    found = claim_tools()
    assert "get_policy_wording" not in found
    whole = Path("context/claims_manual.md").read_text(encoding="utf-8")
    section = found["read_section"].invoke({"document": "claims_manual", "number": 7})
    assert len(section) < len(whole) / 2
    assert json.loads(section)["file"] == "claims_manual.md"


def test_search_finds_the_sections_that_mention_a_word(requests):
    search = claim_tools()["search_documents"]
    found = json.loads(search.invoke({"query": "giraffes"}))["found"]
    assert [(f["name"], f["number"]) for f in found] == [("Claims manual", 7)]
    assert json.loads(search.invoke({"query": "zeppelin"}))["found"] == []


def test_the_payout_tool_goes_through_the_backend(requests):
    run(
        call(
            "calculate_payout",
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
        *decision("refer", 0),
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
