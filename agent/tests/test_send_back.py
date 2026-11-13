from fastapi.testclient import TestClient

from agent import claim as claim_agent
from agent import graph, service
from agent.tests import stubs
from agent.tests.stubs import script
from agent.tracing import Run
from backend import agent_service
from backend.api import app
from backend.tests.signing import as_agent, as_handler

CLAIM = "CLM-1001"
NOTE = "Check the hotel receipt again: one night was already refunded."
RECORD = {
    "kind": "dispatch",
    "n": 1,
    "set_name": None,
    "tiny": False,
    "version": None,
    "round_id": None,
}


def api():
    return TestClient(app, headers=as_agent())


def claim():
    return api().get(f"/api/claims/{CLAIM}").json()


def hold(payout=1200.0):
    return claim_agent.run(
        CLAIM, f"{CLAIM}-first", script(*stubs.decide("approve", payout, CLAIM))
    )


def send_back(monkeypatch, note=NOTE):
    """A handler sends the decision back; the agent isn't asked, so the test can."""
    monkeypatch.setattr(agent_service, "resume", lambda claim_id: None)
    return api().post(
        f"/api/claims/{CLAIM}/send-back", json={"note": note}, headers=as_handler()
    )


def saved():
    built = claim_agent.build(script(), CLAIM, None)
    return built.get_state({"configurable": {"thread_id": claim()["thread_id"]}})


def test_a_sent_back_claim_is_decided_again_and_paid_within_the_limit(
    requests, monkeypatch
):
    hold()
    send_back(monkeypatch)
    report = claim_agent.work(CLAIM, None, script(*stubs.decide("approve", 500.0)))
    assert report == f"{CLAIM}: approve $500.00"
    assert claim()["status"] == "decided"
    assert claim()["payment"]["amount"] == 500.0
    assert claim()["payment"]["signed_off_by"] is None
    messages = saved().values["messages"]
    note = next(m for m in messages if m.type == "human" and NOTE in m.text)
    assert note.text.startswith("Dana Whitfield, a senior handler, sent your decision")
    assert "refer the claim to a handler and give the reason" in note.text
    assert saved().values["model_calls"] == 2


def test_a_new_decision_over_the_limit_waits_for_sign_off_again(requests, monkeypatch):
    hold()
    send_back(monkeypatch)
    report = claim_agent.work(CLAIM, None, script(*stubs.decide("approve", 1000.0)))
    assert report.endswith("waiting for a handler's sign-off")
    assert claim()["status"] == "awaiting_sign_off"
    assert claim()["payment"] is None
    assert claim_agent.paused(CLAIM)
    assert api().get(f"/api/claims/{CLAIM}/sent-back").json()[0]["decision"][
        "payout"
    ] == (1200.0)


def test_the_model_gets_its_full_allowance_again(requests, monkeypatch):
    monkeypatch.setattr(graph, "MODEL_CALLS", 2)
    hold()
    send_back(monkeypatch)
    report = claim_agent.work(CLAIM, None, script(*stubs.decide("approve", 500.0)))
    assert report == f"{CLAIM}: approve $500.00"


def test_a_sent_back_claim_is_taken_once(requests, monkeypatch):
    hold()
    send_back(monkeypatch)
    assert claim_agent.take(CLAIM) is not None
    assert claim_agent.take(CLAIM) is None
    report = claim_agent.work(CLAIM, None, script())
    assert report == f"{CLAIM}: not picked up, another worker is on it"


def test_a_dispatch_during_a_resume_leaves_its_claim_alone(requests, monkeypatch):
    hold()
    send_back(monkeypatch)
    worker = claim_agent.take(CLAIM)
    assert worker is not None
    # While the resume holds the claim, a dispatch's claim agent leaves it.
    report = claim_agent.work(CLAIM, None, script())
    assert report == f"{CLAIM}: not picked up, another worker is on it"
    done = claim_agent.carry_on(
        CLAIM, script(*stubs.decide("approve", 500.0)), None, worker
    )
    assert done == f"{CLAIM}: approve $500.00"


def test_a_send_back_the_agent_never_received_is_worked_by_the_next_dispatch(
    requests, monkeypatch
):
    hold()
    send_back(monkeypatch)
    run = api().post("/api/runs", json=RECORD).json()
    assert CLAIM in [entry["claim_id"] for entry in run["claims"]]
    in_run: Run = {
        "run_id": run["run_id"],
        "kind": "dispatch",
        "version": run["version"],
        "round_id": None,
    }
    report = claim_agent.work(CLAIM, in_run, script(*stubs.decide("refer", 0)))
    assert report == f"{CLAIM}: refer $0.00"
    messages = saved().values["messages"]
    assert any(NOTE in m.text for m in messages if m.type == "human")


def test_a_claim_with_no_saved_progress_starts_afresh_with_the_note(
    requests, monkeypatch
):
    hold()
    send_back(monkeypatch)
    worker = claim_agent.take(CLAIM)
    claim_agent.checkpoints.saver().delete_thread(claim()["thread_id"])
    report = claim_agent.carry_on(
        CLAIM, script(*stubs.decide("refer", 0)), None, worker
    )
    assert report == f"{CLAIM}: refer $0.00"
    first = saved().values["messages"][:2]
    assert first[0].text == f"Decide claim {CLAIM}."
    assert NOTE in first[1].text


def agent_service_client():
    return TestClient(service.app)


def test_resume_takes_a_sent_back_claim_before_it_answers(requests, monkeypatch):
    hold()
    send_back(monkeypatch)
    resumed = []
    monkeypatch.setattr(claim_agent, "carry_on", lambda *args: resumed.append(args))
    answer = agent_service_client().post(f"/claims/{CLAIM}/resume")
    assert answer.status_code == 200
    assert claim()["status"] == "in_progress"
    assert resumed[0][0] == CLAIM
    assert resumed[0][3] is not None
    again = agent_service_client().post(f"/claims/{CLAIM}/resume")
    assert again.status_code == 409
    assert again.json()["detail"] == f"Claim {CLAIM} isn't paused with an answer"
