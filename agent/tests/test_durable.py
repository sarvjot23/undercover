import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage

from agent import claim as claim_agent
from agent import graph, lease, queue, tracing
from agent.tests.stubs import BrokenModel, Stopped, StoppedModel, call, script
from backend import db, runs
from backend.api import app

CLAIM = "CLM-1001"
THREAD = "CLM-1001-first"


def decision(choice="approve", payout=1200.0):
    return call(
        "record_decision",
        claim_id=CLAIM,
        decision=choice,
        payout=payout,
        reasons="The wording settles it. The documents support it.",
        policy_section="3. Trip Delay",
    )


def stop():
    raise Stopped


def api():
    return TestClient(app)


def claim():
    return api().get(f"/api/claims/{CLAIM}").json()


def steps():
    return api().get(f"/api/claims/{CLAIM}/steps").json()


def texts():
    return [(step["kind"], step["text"]) for step in steps()]


def saved_state():
    graph_built = claim_agent.build(script())
    return graph_built.get_state({"configurable": {"thread_id": THREAD}})


def hold():
    return claim_agent.run(CLAIM, THREAD, script(decision()))


def sign_off():
    return api().post(f"/api/claims/{CLAIM}/sign-off", json={"handler_id": "HND-02"})


def test_an_approval_up_to_the_limit_is_paid_straight_after_the_decision(requests):
    answer = claim_agent.run(CLAIM, THREAD, script(decision(payout=420.0)))
    assert answer == "CLM-1001: approve $420.00"
    assert claim()["status"] == "decided"
    assert claim()["payment"]["signed_off_by"] is None
    assert steps()[-1]["text"] == answer


def test_an_approval_over_the_limit_stops_and_waits(requests):
    assert hold().endswith("waiting for a handler's sign-off")
    assert claim()["status"] == "awaiting_sign_off"
    assert claim()["payment"] is None
    assert saved_state().next == ("sign_off",)
    assert claim()["thread_id"] == THREAD
    assert not claim()["agent_working"]


def test_a_sign_off_resumes_the_claim_and_pays_it_once(requests):
    hold()
    assert sign_off().json()["status"] == "in_progress"
    # A broken model proves no model call is needed to pay.
    answer = claim_agent.carry_on(CLAIM, BrokenModel(messages=iter([])))
    assert answer == "CLM-1001: approve $1,200.00"
    assert claim()["status"] == "decided"
    assert claim()["payment"]["amount"] == 1200.0
    assert claim()["payment"]["signed_off_by"] == "HND-02"
    assert claim()["payment"]["signed_off_at"] == claim()["sign_off"]["signed_off_at"]
    assert saved_state().next == ()


def test_resuming_again_changes_nothing(requests):
    hold()
    sign_off()
    claim_agent.carry_on(CLAIM, script())
    paid = claim()["payment"]
    before = texts()
    claim_agent.carry_on(CLAIM, script())
    assert claim()["payment"] == paid
    assert texts() == before


def test_a_held_claim_without_a_sign_off_is_not_resumed(requests):
    hold()
    answer = claim_agent.carry_on(CLAIM, script())
    assert answer.endswith("waiting for a handler's sign-off")
    assert claim()["payment"] is None


def test_a_claim_stopped_partway_carries_on_from_its_last_step(requests):
    stopping = StoppedModel(messages=iter([call("get_claim", claim_id=CLAIM)]))
    with pytest.raises(Stopped):
        claim_agent.run(CLAIM, THREAD, stopping)
    assert claim()["status"] == "in_progress"
    assert claim()["attempts"] == 0
    before = texts()
    assert [kind for kind, _ in before] == ["tool_call", "tool_result"]

    answer = claim_agent.carry_on(CLAIM, script(decision("refer", 0)))
    assert answer == "CLM-1001: refer $0.00"
    assert claim()["attempts"] == 0
    assert claim()["thread_id"] == THREAD
    assert claim()["decision"]["decision"] == "refer"
    assert texts()[:2] == before
    assert len([t for t in texts() if t[1].startswith("get_claim")]) == 2
    messages = saved_state().values["messages"]
    assert len([m for m in messages if m.type == "ai"]) == 2


def stop_on(monkeypatch, kind, *, after, text=""):
    """Kill the process the first time a step of this kind is recorded."""
    original = graph.record_step
    stopped = []

    def stopping(claim_id, step_kind, step_text, key):
        if step_kind == kind and step_text.startswith(text) and not stopped:
            stopped.append(key)
            if after:
                original(claim_id, step_kind, step_text, key)
            raise Stopped
        original(claim_id, step_kind, step_text, key)

    monkeypatch.setattr(graph, "record_step", stopping)


@pytest.mark.parametrize(
    ("kind", "after"),
    [("tool_call", False), ("tool_call", True), ("tool_result", True)],
)
def test_a_restart_repeats_no_step(requests, monkeypatch, kind, after):
    stop_on(monkeypatch, kind, after=after)
    with pytest.raises(Stopped):
        claim_agent.run(
            CLAIM,
            THREAD,
            script(call("get_claim", claim_id=CLAIM), decision("refer", 0)),
        )
    claim_agent.carry_on(CLAIM, script(decision("refer", 0)))
    keys = [step["key"] for step in steps()]
    assert len(keys) == len(set(keys))
    assert [k for k, _ in texts()].count("tool_call") == 2
    assert claim()["decision"]["decision"] == "refer"


def test_a_reply_lost_in_a_crash_never_appears(requests):
    with pytest.raises(Stopped):
        claim_agent.run(CLAIM, THREAD, StoppedModel(messages=iter([])))
    assert steps() == []
    claim_agent.carry_on(CLAIM, script(decision("refer", 0)))
    assert [kind for kind, _ in texts()] == ["tool_call", "tool_result", "answer"]


def test_a_stop_between_the_decision_and_the_payment_pays_once(requests, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(graph, "pay", lambda state: stop())
        with pytest.raises(Stopped):
            claim_agent.run(CLAIM, THREAD, script(decision(payout=420.0)))
    assert claim()["status"] == "in_progress"
    assert claim()["payment"] is None

    claim_agent.carry_on(CLAIM, script())
    assert claim()["status"] == "decided"
    assert claim()["payment"]["amount"] == 420.0
    assert claim()["attempts"] == 0


def test_a_stop_after_the_payment_pays_once_and_repeats_no_step(requests, monkeypatch):
    stop_on(monkeypatch, "tool_result", after=False, text="pay_claim:")
    with pytest.raises(Stopped):
        claim_agent.run(CLAIM, THREAD, script(decision(payout=420.0)))
    paid = claim()["payment"]
    assert paid["amount"] == 420.0

    claim_agent.carry_on(CLAIM, script())
    assert claim()["payment"] == paid
    keys = [step["key"] for step in steps()]
    assert len(keys) == len(set(keys))


def test_a_claim_that_fails_with_an_error_starts_afresh(requests):
    broken = BrokenModel(messages=iter([]))
    assert claim_agent.run(CLAIM, THREAD, broken).endswith("back in the queue")
    assert claim()["attempts"] == 1
    assert claim()["thread_id"] is None
    answer = claim_agent.run(CLAIM, "CLM-1001-second", script(decision("refer", 0)))
    assert answer == "CLM-1001: refer $0.00"
    assert claim()["thread_id"] == "CLM-1001-second"
    assert claim()["attempts"] == 1


def test_an_error_after_the_decision_does_not_send_the_claim_back(
    requests, monkeypatch
):
    def broken(state):
        raise RuntimeError("backend hiccup")

    with monkeypatch.context() as patch:
        patch.setattr(graph, "pay", broken)
        answer = claim_agent.run(CLAIM, THREAD, script(decision(payout=420.0)))
    assert "carries on next time" in answer
    assert claim()["status"] == "in_progress"
    assert claim()["attempts"] == 0
    claim_agent.carry_on(CLAIM, script())
    assert claim()["payment"]["amount"] == 420.0


def test_an_answer_with_no_decision_fails_when_carried_on(requests, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(graph, "standing", lambda claim_id: stop())
        with pytest.raises(Stopped):
            claim_agent.run(CLAIM, THREAD, script(AIMessage(content="Not sure.")))
    assert claim()["status"] == "in_progress"
    assert claim_agent.carry_on(CLAIM, script()).endswith("back in the queue")
    assert claim()["attempts"] == 1


def test_a_claim_with_another_workers_live_lease_is_left_alone(requests, monkeypatch):
    api().post(f"/api/claims/{CLAIM}/start", json={"thread_id": THREAD})
    api().post(f"/api/claims/{CLAIM}/lease", json={"worker": "other"})
    answer = claim_agent.carry_on(CLAIM, script(decision("refer", 0)))
    assert answer == f"{CLAIM}: not picked up, another worker is on it"
    assert steps() == []

    monkeypatch.setattr(db, "now", lambda: "2099-01-01T00:00:00+00:00")
    assert claim_agent.carry_on(CLAIM, script(decision("refer", 0))).endswith("$0.00")


def test_a_second_worker_cannot_start_a_claim(requests):
    api().post(f"/api/claims/{CLAIM}/lease", json={"worker": "other"})
    answer = claim_agent.run(CLAIM, THREAD, script(decision("refer", 0)))
    assert answer == f"{CLAIM}: not started, another worker is on it"
    assert claim()["status"] == "waiting"


def test_the_lease_is_renewed_and_given_up(requests, monkeypatch):
    monkeypatch.setattr(lease, "RENEW_SECONDS", 0.01)
    path = f"/api/claims/{CLAIM}/lease"
    with lease.holding(path) as held:
        assert held
        before = len(requests)
        while requests.count(path) < 3:
            pass
        assert len(requests) > before
        assert api().post(path, json={"worker": "other"}).status_code == 409
    assert api().post(path, json={"worker": "other"}).status_code == 200


def new_run(cap):
    with db.engine().begin() as conn:
        return runs.start(conn, cap)[0]


def test_a_stopped_run_is_finished_by_the_next_within_its_cap(requests):
    run_id = new_run(cap=2)
    with pytest.raises(Stopped):
        queue.run(
            run_id,
            script(
                call(
                    "write_todos",
                    todos=[
                        {"claim_id": CLAIM, "note": "First", "status": "in_progress"}
                    ],
                ),
                call("work_claim", claim_id=CLAIM),
            ),
            lambda claim_id: StoppedModel(messages=iter([])),
        )
    run = api().get("/api/runs/current").json()
    assert run["status"] == "running"
    assert not run["active"]
    assert run["claim_ids"] == [CLAIM]
    assert claim()["status"] == "in_progress"
    thread = claim()["thread_id"]

    with db.engine().begin() as conn:
        again, resumed = runs.start(conn, 9)
    assert (again, resumed) == (run_id, True)

    answer = queue.run(
        run_id,
        script(
            call("work_claim", claim_id="CLM-1008"),
            call("work_claim", claim_id="CLM-1002"),
            call("finish_run", summary="Finished what was stopped."),
            AIMessage(content="Done."),
        ),
        lambda claim_id: script(
            call(
                "record_decision",
                claim_id=claim_id,
                decision="refer",
                payout=0,
                reasons="Needs a handler. The manual says so.",
                policy_section="Claims manual 2.",
            )
        ),
    )
    assert answer == f"Run {run_id} finished: Finished what was stopped."
    assert claim()["thread_id"] == thread
    assert claim()["attempts"] == 0
    assert claim()["status"] == "decided"
    run = api().get("/api/runs/current").json()
    assert run["claim_ids"] == [CLAIM, "CLM-1008"]
    claims = api().get("/api/claims").json()
    assert api().get("/api/claims/CLM-1002").json()["status"] == "waiting"
    assert sum(found["status"] == "decided" for found in claims) == 2


def test_a_second_worker_cannot_work_a_run(requests):
    run_id = new_run(cap=1)
    api().post(f"/api/runs/{run_id}/lease", json={"worker": "other"})
    answer = queue.run(run_id, script())
    assert answer == f"Run {run_id}: another worker is on it"


def test_a_run_carries_on_a_signed_off_claim_first(requests):
    hold()
    sign_off()
    run_id = new_run(cap=1)
    answer = queue.run(
        run_id,
        script(
            call("work_claim", claim_id="CLM-1008"),
            call("finish_run", summary="Paid the claim that was signed off."),
            AIMessage(content="Done."),
        ),
        lambda claim_id: script(
            call(
                "record_decision",
                claim_id=claim_id,
                decision="refer",
                payout=0,
                reasons="Needs a handler. The manual says so.",
                policy_section="Claims manual 2.",
            )
        ),
    )
    assert "finished" in answer
    assert claim()["status"] == "decided"
    assert claim()["payment"]["signed_off_by"] == "HND-02"


def test_a_finished_run_leaves_a_signed_off_claim_to_be_paid(requests):
    hold()
    run_id = new_run(cap=1)
    api().post(f"/api/runs/{run_id}/claims/CLM-1008")
    sign_off()
    api().post(f"/api/runs/{run_id}/fail", json={"reason": "Broke"})
    assert claim()["status"] == "in_progress"
    assert claim()["attempts"] == 0


def test_a_claim_in_a_queue_run_is_traced_as_a_session_of_its_own(
    requests, monkeypatch
):
    class Spy(BaseCallbackHandler):
        parents: list[object | None] = []  # noqa: RUF012

        def on_chain_start(self, serialized, inputs, *, parent_run_id=None, **kwargs):
            self.parents.append(parent_run_id)

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr(tracing, "CallbackHandler", Spy)
    monkeypatch.setattr(tracing, "flush", lambda: None)
    run_id = new_run(cap=1)
    queue.run(
        run_id,
        script(
            call("work_claim", claim_id=CLAIM),
            call("finish_run", summary="One referred."),
            AIMessage(content="Done."),
        ),
        lambda claim_id: script(decision("refer", 0)),
    )
    assert Spy.parents[0] is None
