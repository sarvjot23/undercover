"""The Copilot's graph with a stub model: the loop, its cards, the pause before a
sign-off, the sign-in kept out of everything saved, and its memory of each handler."""

import json

import pytest
from langchain_core.messages import AIMessage
from langgraph.store.base import SearchItem

from agent import checkpoints, copilot_client, copilot_graph, copilot_tools
from agent.tests import copiloting
from agent.tests.serving import serving
from agent.tests.standin_gateway import gateway as standin
from agent.tests.stubs import StubModel, call, script
from agent.tests.test_memory import WHEN, StandinStore
from backend.tests import signing

CLAIM = "CLM-1003"


@pytest.fixture
def copilot(requests, monkeypatch):
    """The app on SQLite with the context layer, as the Copilot reaches them."""
    found = copiloting.Copilot()
    found.install(monkeypatch)
    monkeypatch.setenv("UNDERCOVER_API_KEY", signing.AGENT_KEY)
    return found


def answered(text, cost=0.002):
    """The model's answer, with the cost OpenRouter reports."""
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": cost}
    return AIMessage(content=text, response_metadata={"token_usage": usage})


def last_turn(context):
    return copiloting.conversation(context)["turns"][-1]


def test_a_lookup_then_an_answer(copilot):
    context = copiloting.begin("What does CLM-1001 say?")
    llm = script(call("get_claim", claim_id="CLM-1001"), answered("It's a delay."))
    copilot_graph.turn(context, "What does CLM-1001 say?", llm)
    turn = last_turn(context)
    assert turn["status"] == "done"
    assert turn["answer"] == "It's a delay."
    assert (turn["model_calls"], turn["cost"]) == (2, 0.002)
    [card] = turn["steps"]
    assert (card["kind"], card["tool"], card["input"]) == (
        "claims",
        "get_claim",
        "CLM-1001",
    )
    assert card["state"] == "done"
    assert "Maya Patel" in card["answer"]


def test_a_context_layer_card_names_its_file_and_owner(copilot):
    context = copiloting.begin("What's a named storm?")
    llm = script(
        call("lookup_term", term="named storm"), answered("A storm with a name.")
    )
    copilot_graph.turn(context, "What's a named storm?", llm)
    [card] = last_turn(context)["steps"]
    assert (card["kind"], card["tool"], card["state"]) == (
        "context",
        "lookup_term",
        "done",
    )
    assert card["sources"]
    assert {"file", "owner"} <= set(card["sources"][0])


def test_a_refusal_reaches_the_model_and_shows_on_its_card(copilot):
    context = copiloting.begin("Look at CLM-9999")
    llm = script(
        call("get_claim", claim_id="CLM-9999"), answered("There's no such claim.")
    )
    copilot_graph.turn(context, "Look at CLM-9999", llm)
    [card] = last_turn(context)["steps"]
    assert card["state"] == "refused"
    assert card["reason"] == "Refused (404): No claim CLM-9999"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("sign_off_claim", {"claim_id": CLAIM}),
        ("send_back", {"claim_id": CLAIM, "note": "Look again"}),
    ],
)
def test_marcus_is_refused_in_code_before_any_call(copilot, tool, args):
    copiloting.hold_for_sign_off()
    context = copiloting.begin("Sign it off", email=signing.MARCUS)
    before = len(copilot.requests)
    llm = script(call(tool, **args), answered("You can't do that."))
    copilot_graph.turn(context, "Sign it off", llm)
    [card] = last_turn(context)["steps"]
    assert card["state"] == "refused"
    assert "Marcus Oyelaran can't sign off payouts over the limit" in card["reason"]
    paths = [r.url.path for r in copilot.requests[before:]]
    assert not any(path.startswith("/api/claims") for path in paths)


def test_the_sign_off_pauses_with_a_card_from_our_records(copilot):
    copiloting.hold_for_sign_off()
    context = copiloting.begin("Sign off CLM-1003")
    llm = script(
        AIMessage(
            content="I'll pay $9.00.",
            tool_calls=[
                {
                    "name": "sign_off_claim",
                    "args": {"claim_id": CLAIM},
                    "id": "call-sign",
                }
            ],
        ),
    )
    copilot_graph.turn(context, "Sign off CLM-1003", llm)
    turn = last_turn(context)
    assert turn["status"] == "waiting"
    assert turn["confirmation"] == {
        "claim_id": CLAIM,
        "customer": "Aiko Tanaka",
        "amount": 3750.0,
        "reason": "The wording settles it. The documents support it.",
        "policy_section": "3. Trip Delay",
    }
    with copiloting.as_agent() as agent:
        assert agent.get(f"/api/claims/{CLAIM}").json()["status"] == "awaiting_sign_off"


def pause_on_sign_off(copilot):
    """A turn that looked the claim up, then paused before signing it off."""
    copiloting.hold_for_sign_off()
    context = copiloting.begin("Sign off CLM-1003")
    llm = script(
        call("get_claim", claim_id=CLAIM), call("sign_off_claim", claim_id=CLAIM)
    )
    copilot_graph.turn(context, "Sign off CLM-1003", llm)
    return context


def test_a_fresh_copilot_carries_the_pause_on_and_pays_once(copilot):
    context = pause_on_sign_off(copilot)
    looked_up = [r for r in copilot.requests if r.url.path == f"/api/claims/{CLAIM}"]
    copiloting.answer_card(context, True)
    llm = script(answered("Paid."))  # a freshly built graph, on the saved state
    copilot_graph.answer(context, True, llm)
    turn = last_turn(context)
    assert turn["status"] == "done"
    assert turn["answer"] == "Paid."
    assert [s["tool"] for s in turn["steps"]] == [
        "get_claim",
        "sign_off_claim",
        "sign_off",
    ]
    assert turn["steps"][-1]["answer"] == "Signed off CLM-1003 and paid $3,750.00"
    after = [r for r in copilot.requests if r.url.path == f"/api/claims/{CLAIM}"]
    assert len(after) == len(looked_up)  # nothing before the pause ran again
    with copiloting.as_agent() as agent:
        claim = agent.get(f"/api/claims/{CLAIM}").json()
    assert claim["payment"]["signed_off_by"] == "HND-01"
    signs = [r for r in copilot.requests if r.url.path.endswith("/sign-off")]
    assert len(signs) == 1


def test_cancel_pays_nothing_and_the_model_hears_it(copilot):
    context = pause_on_sign_off(copilot)
    copiloting.answer_card(context, False)
    llm = script(answered("I haven't signed it off. What would you like instead?"))
    copilot_graph.answer(context, False, llm)
    with copiloting.as_agent() as agent:
        assert agent.get(f"/api/claims/{CLAIM}").json()["status"] == "awaiting_sign_off"
    saved = copilot_graph.build(lambda: llm, [], checkpoints.saver()).get_state(
        copilot_graph.config_for(context)
    )
    told = saved.values["messages"][-2].text
    assert "pressed Cancel" in told


def test_the_sign_in_is_saved_nowhere_and_the_key_never_sent(copilot):
    store = StandinStore()
    context = copiloting.begin("What needs me?", memory=store)
    llm = script(call("list_claims"), answered("Nothing yet."))
    copilot_graph.turn(context, "What needs me?", llm)
    saver = checkpoints.saver()
    config = copilot_graph.config_for(context)
    everything = [repr(c) for c in saver.list(config)]
    assert all(context.token not in saved for saved in everything)
    assert context.token not in json.dumps(config)
    assert context.token not in json.dumps(last_turn(context))
    assert context.token not in repr(store.events)
    assert all("X-API-Key" not in r.headers for r in copilot.requests)
    assert all(
        r.headers["Authorization"] == f"Bearer {context.token}"
        for r in copilot.requests
    )


def test_the_connection_never_carries_the_agents_key(monkeypatch):
    monkeypatch.setenv("UNDERCOVER_API_KEY", "the-agents-key")
    connected = copilot_client.connect("a-sign-in")
    assert "X-API-Key" not in connected.headers
    assert connected.headers["Authorization"] == "Bearer a-sign-in"


def test_at_25_model_calls_the_turn_ends_saying_so(copilot):
    context = copiloting.begin("Keep going")
    llm = script(*[call("get_settings") for _ in range(25)])
    copilot_graph.turn(context, "Keep going", llm)
    turn = last_turn(context)
    assert turn["status"] == "done"
    assert turn["model_calls"] == 25
    assert turn["answer"] == copilot_graph.TOO_MANY_CALLS


class Watching(StubModel):
    """A stub model that keeps what it was given each time it's called."""

    seen: list = []

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


def watching(*replies):
    return Watching(messages=iter(replies), seen=[])


def test_a_turn_after_one_that_stopped_mid_step_starts_cleanly(copilot):
    context = copiloting.begin("First")
    graph = copilot_graph.build(script, [], checkpoints.saver())
    config = copilot_graph.config_for(context)
    lost = {"name": "list_claims", "args": {}, "id": "lost"}
    stopped = AIMessage(content="", tool_calls=[lost])
    graph.update_state(
        config, {"messages": [stopped], "asked": "First"}, as_node="model"
    )
    copiloting.fail(context, "stopped")
    second = copiloting.follow_up(context, "Second")
    llm = watching(answered("Fine."))
    copilot_graph.turn(second, "Second", llm)
    history = llm.seen[0][1:]
    kinds = [type(m).__name__ for m in history]
    assert kinds[-3:] == ["AIMessage", "ToolMessage", "HumanMessage"]
    assert history[-2].text == copilot_graph.STOPPED_PARTWAY
    assert last_turn(second)["answer"] == "Fine."


def remembered(text):
    return SearchItem(
        namespace=("handlers", "HND-01", "preferences"),
        key="r1",
        value={"content": text},
        created_at=WHEN,
        updated_at=WHEN,
    )


def test_the_memory_lookup_is_a_card_and_the_turn_is_saved(copilot):
    store = StandinStore(found=[remembered("Dana likes amounts first.")])
    context = copiloting.begin("What needs me?", memory=store)
    llm = watching(answered("Nothing needs you."))
    copilot_graph.turn(context, "What needs me?", llm)
    assert store.searches == [(("handlers", "HND-01"), "What needs me?", 5)]
    [card] = last_turn(context)["steps"]
    assert (card["kind"], card["tool"]) == ("memory", "recall_memory")
    assert card["answer"] == "Dana likes amounts first."
    assert "Dana likes amounts first." in llm.seen[0][0].text
    namespace = (context.handler["handler_id"], context.conversation_id)
    assert [(ns, m.text) for ns, m in store.events] == [
        (namespace, "What needs me?"),
        (namespace, "Nothing needs you."),
    ]


def test_with_memory_off_there_is_no_card_and_no_save(copilot):
    context = copiloting.begin("Hello")
    copilot_graph.turn(context, "Hello", script(answered("Hello, Dana.")))
    assert last_turn(context)["steps"] == []


def test_a_memory_that_cant_be_reached_doesnt_stop_the_turn(copilot):
    store = StandinStore(broken=True)
    context = copiloting.begin("Hello", memory=store)
    copilot_graph.turn(context, "Hello", script(answered("Hello, Dana.")))
    assert last_turn(context)["status"] == "done"


def test_on_the_gateway_only_the_context_layers_tools_load(requests, monkeypatch):
    monkeypatch.setattr(copilot_tools, "SigV4Auth", lambda session: None)
    with serving(standin(lambda name, arguments: False)) as url:
        found = copilot_tools.context_tools(f"{url}/mcp", None)
        answer = next(t for t in found if t.name == "get_claim_rules").invoke({})
    assert sorted(t.name for t in found) == sorted(
        [
            "lookup_term",
            "describe_fields",
            "get_plan",
            "get_claim_rules",
            "search_reference_data",
            "search_documents",
            "read_section",
        ]
    )
    assert "file" in answer
