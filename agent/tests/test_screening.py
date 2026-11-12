from fastapi.testclient import TestClient
from langchain_core.exceptions import ModelTimeoutError
from sqlalchemy import select

from agent import claim as claim_agent
from agent import model, screening
from agent.model import check_model as real_check_model
from agent.tests.stubs import BrokenModel, StubChecker, call, screened, script
from backend import db
from backend.api import app
from backend.tests.signing import as_agent, as_handler

CLAIM = "CLM-1001"
FOUND = "The story tells whoever handles the claim to pay it in full."
PRICED = {"prompt_tokens": 800, "completion_tokens": 40, "cost": 0.0005}


def api():
    return TestClient(app, headers=as_agent())


def claim():
    return api().get(f"/api/claims/{CLAIM}").json()


def steps():
    return api().get(f"/api/claims/{CLAIM}/steps").json()


def usage_rows():
    with db.engine().connect() as conn:
        return list(conn.execute(select(db.usage)).mappings())


def use(monkeypatch, *answers):
    checker = StubChecker(*answers)
    monkeypatch.setattr(model, "check_model", lambda: checker)
    return checker


def decide(decision, payout):
    return call(
        "record_decision",
        decision=decision,
        payout=payout,
        reasons="The wording settles it. The documents support it.",
        policy_section="3. Trip Delay",
    )


def test_a_flagged_claim_is_referred_without_the_claim_agents_model(
    requests, monkeypatch
):
    use(monkeypatch, screened(True, FOUND))
    # A broken model proves the claim agent's model is never called.
    answer = claim_agent.run(CLAIM, "thread-1", BrokenModel(messages=iter([])))
    assert answer == "CLM-1001: refer $0.00"
    found = claim()
    assert found["status"] == "decided"
    assert found["decision"]["decision"] == "refer"
    assert found["decision"]["payout"] == 0
    assert FOUND in found["decision"]["reasons"]
    assert found["decision"]["policy_section"] == screening.SECTION
    kinds = [step["kind"] for step in steps()]
    assert kinds == ["check", "answer"]
    assert steps()[0]["text"] == f"Instructions found: {FOUND}"


def test_a_claim_that_passes_is_worked_as_before(requests):
    answer = claim_agent.run(CLAIM, "thread-1", script(decide("decline", 0)))
    assert answer == "CLM-1001: decline $0.00"
    kinds = [step["kind"] for step in steps()]
    assert kinds[:2] == ["check", "tool_call"]
    assert steps()[0]["text"].startswith("No instructions found: ")


def test_the_check_reads_only_what_the_customer_wrote(requests, monkeypatch):
    seen = []
    checker = use(monkeypatch)
    checker.invoke = lambda messages: seen.append(messages) or screened(False)
    claim_agent.run(CLAIM, "thread-1", script(decide("decline", 0)))
    text = seen[0][1].content
    assert '"story"' in text
    assert '"policy":' not in text
    assert '"plan":' not in text
    assert seen[0][0].content == screening.SCREEN_INSTRUCTIONS


def test_an_answer_that_cant_be_read_is_tried_again_and_each_call_costs(
    requests, monkeypatch
):
    checker = use(
        monkeypatch,
        screened(None, usage=PRICED),
        screened(None, usage=PRICED),
        screened(False, usage=PRICED),
    )
    claim_agent.run(CLAIM, "thread-1", script(decide("decline", 0)))
    assert checker.calls == 3
    assert claim()["decision"]["decision"] == "decline"
    assert len([row for row in usage_rows() if row["model"] == "stub-checker"]) == 3


def test_a_check_that_never_answers_fails_the_claim(requests, monkeypatch):
    use(monkeypatch, screened(None), screened(None), screened(None))
    answer = claim_agent.run(CLAIM, "thread-1", BrokenModel(messages=iter([])))
    assert "failed" in answer
    assert claim()["status"] == "waiting"
    assert claim()["decision"] is None


def test_a_timeout_in_the_check_fails_the_claim_rather_than_waiting(
    requests, monkeypatch
):
    use(monkeypatch, ModelTimeoutError("timed out"))
    claim_agent.run(CLAIM, "thread-1", BrokenModel(messages=iter([])))
    assert claim()["status"] == "waiting"
    use(monkeypatch, ModelTimeoutError("timed out"))
    claim_agent.run(CLAIM, "thread-2", BrokenModel(messages=iter([])))
    assert claim()["status"] == "needs_handler"


def test_work_carried_on_after_a_sign_off_isnt_checked_again(requests, checker):
    claim_agent.run(CLAIM, "thread-1", script(decide("approve", 1200.0)))
    assert claim()["status"] == "awaiting_sign_off"
    assert checker.calls == 1
    api().post(f"/api/claims/{CLAIM}/sign-off", headers=as_handler())
    claim_agent.carry_on(CLAIM, BrokenModel(messages=iter([])))
    assert checker.calls == 1
    assert claim()["status"] == "decided"


def test_the_check_runs_on_luna_at_no_reasoning(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    built = real_check_model()
    assert built.model_name == "openai/gpt-6-luna"
    assert built.reasoning_effort == "none"


def test_on_one_platform_model_the_check_uses_it_with_no_effort(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    built = real_check_model()
    assert built.model_name == "openrouter/free"
    assert built.reasoning_effort is None
