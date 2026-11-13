import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.base import SearchItem
from langgraph.store.memory import InMemoryStore

from agent import claim as claim_agent
from agent import memory, model, routes, tools
from agent.tests import stubs
from agent.tests.stubs import StubChecker, call, screened, script
from agent.tracing import Run
from backend.api import app
from backend.tests.signing import as_agent, as_handler

CLAIM = "CLM-1005"
CUSTOMER = "CUS-3005"
WHEN = datetime(2026, 11, 1, tzinfo=UTC)


class StandinStore(InMemoryStore):
    """AgentCore Memory as the agent sees it: the events it's given, and the
    memories a search finds."""

    def __init__(self, found=(), broken=False):
        super().__init__()
        self.events = []
        self.searches = []
        self.found = list(found)
        self.broken = broken

    def put(self, namespace, key, value, index=None, *, ttl=None):
        if self.broken:
            raise ConnectionError("AgentCore can't be reached")
        self.events.append((namespace, value["message"]))

    def search(self, namespace_prefix, /, *, query=None, limit=10, **kwargs):
        if self.broken:
            raise ConnectionError("AgentCore can't be reached")
        self.searches.append((namespace_prefix, query, limit))
        return self.found


def remembered(text, *paths):
    return SearchItem(
        namespace=("customers", CUSTOMER),
        key=text,
        value={"content": text, "namespaces": list(paths)},
        created_at=WHEN,
        updated_at=WHEN,
        score=0.9,
    )


@pytest.fixture
def memory_on(monkeypatch):
    """Memory turned on with a stand-in for AgentCore Memory."""
    store = StandinStore()
    monkeypatch.setenv("UNDERCOVER_MEMORY_ID", "memory-test")
    monkeypatch.setattr(memory, "AgentCoreMemoryStore", lambda **kwargs: store)
    return store


def api():
    return TestClient(app, headers=as_agent())


def steps(claim_id=CLAIM):
    return api().get(f"/api/claims/{claim_id}/steps").json()


def approve(payout=150.0, claim_id=CLAIM):
    return claim_agent.run(
        claim_id,
        f"{claim_id}-first",
        script(*stubs.decide("approve", payout, claim_id)),
    )


def test_a_decision_saves_the_claim_and_the_decision(requests, memory_on):
    assert approve() == f"{CLAIM}: approve $150.00"
    (said_on, said), (decided_on, decided) = memory_on.events
    assert said_on == decided_on == (CUSTOMER, CLAIM)
    assert isinstance(said, HumanMessage)
    assert "Passport eaten by a giraffe at breakfast" in said.text
    assert "passport" in said.text
    assert "2026-07-01" in said.text
    assert "Nairobi, Kenya" in said.text
    assert "Emergency passport fee $165.00" in said.text
    assert isinstance(decided, AIMessage)
    assert "approve" in decided.text
    assert "$150.00" in decided.text
    assert "3. Trip Delay" in decided.text
    assert stubs.FIELDS["reasons"] in decided.text


def test_the_story_and_the_documents_stay_on_the_claim(requests, memory_on):
    approve()
    claim = api().get(f"/api/claims/{CLAIM}").json()
    said = memory_on.events[0][1].text
    assert claim["story"][:60] not in said
    assert claim["documents"][0]["content"][:60] not in said


def test_the_save_is_a_step_on_the_claim(requests, memory_on):
    approve()
    saved = [step for step in steps() if step["kind"] == "memory_save"]
    assert len(saved) == 1
    assert "Passport eaten by a giraffe" in saved[0]["text"]


def test_nothing_is_saved_for_a_claim_the_check_referred(
    requests, memory_on, monkeypatch
):
    checker = StubChecker(screened(True, "The story asks to be paid in full."))
    monkeypatch.setattr(model, "check_model", lambda: checker)
    assert approve().endswith("refer $0.00")
    assert memory_on.events == []


def evaluation_copy():
    created = api().post(
        "/api/runs",
        json={
            "kind": "evaluation",
            "n": 1,
            "set_name": "evaluation",
            "tiny": True,
            "version": None,
            "round_id": None,
        },
    )
    return created.json()


@pytest.mark.parametrize("in_evaluation", [True, False])
def test_nothing_is_saved_for_an_evaluations_copy(requests, memory_on, in_evaluation):
    created = evaluation_copy()
    copy = created["claims"][0]["claim_id"]
    run: Run = {
        "run_id": created["run_id"],
        "kind": "evaluation",
        "version": 1,
        "round_id": None,
    }
    claim_agent.work(
        copy,
        run if in_evaluation else None,
        script(*stubs.decide("refer", 0, copy)),
    )
    assert api().get(f"/api/claims/{copy}").json()["decision"] is not None
    assert memory_on.events == []


def claim_tools(store, claim_id="CLM-1006"):
    found = tools.ClaimContext(
        claim_id, "POL-2006", CUSTOMER, 1, None, routes.choose(), store
    )
    return {tool.name: tool for tool in tools.for_claim(found)}


def test_a_search_stays_with_the_claims_customer_and_leaves_out_this_claim():
    store = StandinStore(
        found=[
            remembered(
                "Oliver lost his passport to a giraffe in Nairobi.",
                f"/customers/{CUSTOMER}/facts/",
            ),
            remembered(
                "CLM-1006: hit by a coconut.",
                f"/customers/{CUSTOMER}/claims/CLM-1006/",
            ),
        ]
    )
    answer = claim_tools(store)["search_memory"].invoke({"query": "passport"})
    assert store.searches == [(("customers", CUSTOMER), "passport", 5)]
    assert answer == "Oliver lost his passport to a giraffe in Nairobi."


def test_a_search_with_nothing_found_says_so():
    answer = claim_tools(StandinStore())["search_memory"].invoke({"query": "x"})
    assert answer == "Nothing remembered about this customer yet."


def test_a_failed_search_is_a_refusal():
    answer = claim_tools(StandinStore(broken=True))["search_memory"].invoke(
        {"query": "passport"}
    )
    assert answer == "Refused by AgentCore Memory: AgentCore can't be reached"


def test_a_search_by_the_model_is_a_memory_step(requests, memory_on):
    memory_on.found = [remembered("A first claim, approved.", "/customers/x/facts/")]
    claim_agent.run(
        CLAIM,
        f"{CLAIM}-first",
        script(
            call("search_memory", query="earlier claims"),
            *stubs.decide("refer", 0, CLAIM),
        ),
    )
    searched = [step for step in steps() if step["kind"] == "memory_search"]
    assert searched[0]["text"] == (
        "Searched memory for 'earlier claims': A first claim, approved."
    )


def test_no_memory_tool_with_memory_off(requests, monkeypatch):
    monkeypatch.delenv("UNDERCOVER_MEMORY_ID", raising=False)
    assert memory.for_run(None) is None
    assert "search_memory" not in claim_tools(None)


def test_no_memory_in_an_evaluation(memory_on):
    assert memory.for_run("evaluation") is None
    assert memory.for_run("dispatch") is memory_on
    assert memory.for_run(None) is memory_on


def test_the_memory_is_agentcores_in_the_aws_clis_region(monkeypatch):
    made = []
    monkeypatch.setenv("UNDERCOVER_MEMORY_ID", "memory-test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setattr(
        memory, "AgentCoreMemoryStore", lambda **kwargs: made.append(kwargs)
    )
    memory.for_run("dispatch")
    assert made == [{"memory_id": "memory-test", "region_name": "us-west-2"}]


def test_a_store_that_fails_leaves_the_decision(requests, memory_on, caplog):
    memory_on.broken = True
    with caplog.at_level(logging.WARNING):
        assert approve() == f"{CLAIM}: approve $150.00"
    claim = api().get(f"/api/claims/{CLAIM}").json()
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 150.0
    assert f"Couldn't save {CLAIM} to memory" in caplog.text
    assert not [step for step in steps() if step["kind"] == "memory_save"]


def test_remember_runs_once(requests, memory_on):
    held = approve(1200.0)
    assert held.endswith("waiting for a handler's sign-off")
    assert len(memory_on.events) == 2
    api().post(f"/api/claims/{CLAIM}/sign-off", headers=as_handler())
    claim_agent.carry_on(CLAIM, script())
    assert len(memory_on.events) == 2
    assert len([s for s in steps() if s["kind"] == "memory_save"]) == 1
