from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent import client, queue
from agent.tests.stubs import BrokenModel, call, script
from backend import db, runs
from backend.api import app


def new_run(cap):
    with db.engine().begin() as conn:
        return runs.start(conn, cap)


def api():
    return TestClient(app)


def status(claim_id):
    return api().get(f"/api/claims/{claim_id}").json()["status"]


def decided(claim_id):
    """A claim handler that refers the claim."""
    return script(
        call(
            "record_decision",
            claim_id=claim_id,
            decision="refer",
            payout=0,
            reasons="Needs a handler's judgment. The manual says to refer.",
            policy_section="Claims manual 2. The three decisions",
        ),
        AIMessage(content="Referred."),
    )


def todos(*items):
    return call(
        "write_todos",
        todos=[
            {"claim_id": claim_id, "note": "A claim", "status": state}
            for claim_id, state in items
        ],
    )


def work(*claim_ids):
    return [call("work_claim", claim_id=claim_id) for claim_id in claim_ids]


def finish(summary="All referred."):
    return [call("finish_run", summary=summary), AIMessage(content="Done.")]


def test_a_capped_run_works_its_claims_in_the_agents_order(requests):
    run_id = new_run(cap=2)
    answer = queue.run(
        run_id,
        script(
            call("list_waiting_claims"),
            todos(("CLM-1020", "to_do"), ("CLM-1003", "to_do")),
            *work("CLM-1020", "CLM-1003"),
            todos(("CLM-1020", "done"), ("CLM-1003", "done")),
            *finish("Two claims referred."),
        ),
        decided,
    )
    assert answer == f"Run {run_id} finished: Two claims referred."
    run = api().get("/api/runs/current").json()
    assert run["claim_ids"] == ["CLM-1020", "CLM-1003"]
    assert [todo["status"] for todo in run["todos"]] == ["done", "done"]
    claims = api().get("/api/claims").json()
    assert sum(claim["status"] == "waiting" for claim in claims) == 23
    steps = api().get("/api/claims/CLM-1020/steps").json()
    assert all("CLM-1020" in step["text"] for step in steps if step["kind"] != "answer")
    assert api().get("/api/claims/CLM-1001/steps").json() == []


def test_a_failed_claim_goes_back_and_is_tried_again(requests):
    run_id = new_run(cap=1)
    handlers = iter([BrokenModel(messages=iter([])), decided("CLM-1001")])
    answer = queue.run(
        run_id,
        script(*work("CLM-1001", "CLM-1001"), *finish()),
        lambda claim_id: next(handlers),
    )
    assert "finished" in answer
    claim = api().get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["attempts"] == 1


def test_a_claim_that_fails_twice_is_left_for_a_handler(requests):
    run_id = new_run(cap=1)
    answer = queue.run(
        run_id,
        script(
            *work("CLM-1001", "CLM-1001"),
            todos(("CLM-1001", "left_for_handler")),
            *finish("One claim left for a handler."),
        ),
        lambda claim_id: BrokenModel(messages=iter([])),
    )
    assert "finished" in answer
    assert status("CLM-1001") == "needs_handler"
    run = api().get("/api/runs/current").json()
    assert run["todos"][0]["status"] == "left_for_handler"


def test_the_agent_is_made_to_work_a_claim_it_missed(requests):
    run_id = new_run(cap=2)
    answer = queue.run(
        run_id,
        script(
            *work("CLM-1001"),
            call("finish_run", summary="Done too soon."),
            *work("CLM-1002"),
            *finish(),
        ),
        decided,
    )
    assert "finished: All referred." in answer
    assert status("CLM-1002") == "decided"


def test_the_cap_holds_whatever_the_agent_does(requests):
    run_id = new_run(cap=2)
    queue.run(
        run_id, script(*work("CLM-1001", "CLM-1002", "CLM-1003"), *finish()), decided
    )
    assert status("CLM-1003") == "waiting"
    assert api().get("/api/runs/current").json()["claim_ids"] == [
        "CLM-1001",
        "CLM-1002",
    ]


def test_a_broken_queue_agent_fails_the_run(requests):
    run_id = new_run(cap=2)
    answer = queue.run(run_id, BrokenModel(messages=iter([])))
    assert answer.startswith(f"Run {run_id} failed: The queue agent's run failed")
    claims = api().get("/api/claims").json()
    assert all(claim["status"] != "in_progress" for claim in claims)


def test_a_queue_agent_that_stops_early_fails_the_run(requests):
    run_id = new_run(cap=2)
    answer = queue.run(run_id, script(AIMessage(content="I'll stop here.")))
    assert answer == (
        f"Run {run_id} failed: The queue agent stopped without finishing the run"
    )


def test_waiting_claims_are_listed_for_the_agent(requests):
    run_id = new_run(cap=1)
    listing = next(
        t
        for t in queue.tools(client.backend(), run_id, decided)
        if t.name == "list_waiting_claims"
    ).invoke({})
    assert listing.splitlines()[0] == "CLM-1001 trip_delay $420.00 submitted 2026-06-24"
    assert len(listing.splitlines()) == 25
