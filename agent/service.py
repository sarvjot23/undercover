"""The agent's service, its entry point: uv run -m uvicorn agent.service:app."""

import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import claim, client, dispatcher, graph, improver_client, rounds, tracing

BACKEND_WAIT_TRIES = 30
BACKEND_WAIT_SECONDS = 1.0
MAX_AGENTS = 25
ALREADY_RUNNING = "A dispatch or evaluation is already running"

# Held while a dispatch, an evaluation or a stretch of a round's work goes on: one
# at a time. A round's evaluations are part of its work. `doing` names what holds
# it, for a refusal.
busy = threading.Lock()
doing = {"what": ""}


def take(what: str) -> None:
    """Take the service for some work, or refuse with a 409 naming what's running."""
    if not busy.acquire(blocking=False):
        raise HTTPException(409, doing["what"] or ALREADY_RUNNING)
    doing["what"] = what


def let_go() -> None:
    """Free the service for the next piece of work."""
    doing["what"] = ""
    busy.release()


class ClaimRun(BaseModel):
    """The thread to start a claim on."""

    thread_id: str


class DispatchStart(BaseModel):
    """How many claim agents a dispatch works with at once."""

    n: int = Field(ge=1, le=MAX_AGENTS)


class EvaluationStart(BaseModel):
    """The labelled set to evaluate, whole or its tiny claims, and N."""

    set_name: Literal["evaluation", "held_out"]
    tiny: bool
    n: int = Field(ge=1, le=MAX_AGENTS)


class RoundStart(BaseModel):
    """The handler who starts a round."""

    handler_id: str


class RoundDecision(BaseModel):
    """A handler's approval or rejection of the improver's proposal."""

    decision: Literal["approve", "reject"]
    message: str
    handler_id: str


def backend_claims() -> list[dict[str, Any]]:
    """Return the queue once the backend is up, or nothing if it never comes."""
    for _ in range(BACKEND_WAIT_TRIES):
        try:
            with client.backend() as backend:
                return backend.get("/api/claims").raise_for_status().json()
        except httpx.HTTPError:
            time.sleep(BACKEND_WAIT_SECONDS)
    return []


def stop_leftover_run() -> None:
    """Mark a dispatch or evaluation left running from before as stopped."""
    with client.backend() as backend:
        running = backend.get("/api/runs/running").json()
        if running:
            backend.post(f"/api/runs/{running['run_id']}/stop")


def halt_leftover_round() -> None:
    """Mark a round left working from before as stopped. A round waiting for a
    handler is left as it is: its progress is saved and it carries on later."""
    found = improver_client.open_round()
    if found and found["status"] == "working":
        improver_client.halt(found["round_id"])


def pick_up_signed_off() -> None:
    """Stop what was left running, pay what was signed off, and warm up for the next.

    The queue leaves out evaluation copies, so none is ever picked up here.
    """
    claims = backend_claims()
    if not claims:
        return
    stop_leftover_run()
    halt_leftover_round()
    config = tracing.config("warm-up", graph.RECURSION_LIMIT, None)
    claim.build(None, None).get_state(config)
    for found in claims:
        if found["status"] == "in_progress" and found["signed_off"]:
            claim.carry_on(found["claim_id"])


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Pick up signed-off claims in the background, so startup doesn't wait for them."""
    threading.Thread(target=pick_up_signed_off, daemon=True).start()
    yield


app = FastAPI(title="UnderCover Agent", lifespan=lifespan)


def work_run(record: dict[str, Any], n: int) -> None:
    """Create the run through the backend and work it, then free the service."""
    try:
        with client.backend() as backend:
            created = backend.post("/api/runs", json=record).json()
        doing["what"] = f"{created['kind'].capitalize()} {created['run_id']} is running"
        run: tracing.Run = {
            "run_id": created["run_id"],
            "kind": created["kind"],
            "version": created["version"],
            "round_id": created["round_id"],
        }
        dispatcher.dispatch(run, n)
    finally:
        let_go()


def start(
    record: dict[str, Any], n: int, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Take on a run on the current version and work it in the background, or 409."""
    take(
        f"A{'n' if record['kind'] == 'evaluation' else ''} {record['kind']} is starting"
    )
    begin = {**record, "n": n, "version": None, "round_id": None}
    background_tasks.add_task(work_run, begin, n)
    return {"accepted": True}


@app.get("/health", operation_id="agent_health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}


@app.post("/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(
    begin: DispatchStart, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Dispatch the queue with N claim agents at once."""
    record = {"kind": "dispatch", "set_name": None, "tiny": False}
    return start(record, begin.n, background_tasks)


@app.post("/evaluations", operation_id="start_evaluation", status_code=202)
def start_evaluation(
    begin: EvaluationStart, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Evaluate the agent on copies of a labelled set with N claim agents at once."""
    record = {"kind": "evaluation", "set_name": begin.set_name, "tiny": begin.tiny}
    return start(record, begin.n, background_tasks)


@app.post("/claims/{claim_id}/resume", operation_id="resume_claim")
def resume_claim(claim_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Pick a signed-off claim back up from where it stopped."""
    background_tasks.add_task(claim.carry_on, claim_id)
    return {"claim_id": claim_id, "accepted": True}


@app.post("/claims/{claim_id}/run", operation_id="work_claim")
def work_claim(
    claim_id: str, begin: ClaimRun, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Start the agent on one waiting claim."""
    background_tasks.add_task(claim.run, claim_id, begin.thread_id)
    return {"claim_id": claim_id, "accepted": True}


def work_round(round_id: int, stretch: Callable[[], None]) -> None:
    """Do a stretch of a round's work, then free the service.

    If it breaks, the round is marked stopped rather than left working.
    """
    try:
        stretch()
    except Exception:
        if improver_client.find(round_id)["status"] == "working":
            improver_client.halt(round_id)
        raise
    finally:
        let_go()


@app.post("/rounds", operation_id="start_round", status_code=202)
def start_round(begin: RoundStart, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Open a round and work it: its first evaluations, then the improver."""
    take("A round is starting")
    try:
        found = improver_client.create(begin.handler_id)
    except improver_client.Refused as refused:
        let_go()
        raise HTTPException(refused.status, refused.detail) from None
    round_id = found["round_id"]
    doing["what"] = f"Round {round_id} is working"
    background_tasks.add_task(work_round, round_id, lambda: rounds.work(round_id))
    return {"accepted": True, "round_id": round_id}


@app.post(
    "/rounds/{round_id}/decision", operation_id="decide_on_proposal", status_code=202
)
def decide_on_proposal(
    round_id: int, decision: RoundDecision, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Record a handler's decision on the proposal, then carry the improver on."""
    take(f"Round {round_id} is working")
    try:
        improver_client.decide(
            round_id, decision.decision, decision.message, decision.handler_id
        )
    except improver_client.Refused as refused:
        let_go()
        raise HTTPException(refused.status, refused.detail) from None
    background_tasks.add_task(
        work_round,
        round_id,
        lambda: rounds.resume(round_id, decision.decision, decision.message),
    )
    return {"accepted": True, "round_id": round_id}


@app.post("/rounds/{round_id}/stop", operation_id="stop_round")
def stop_round(round_id: int) -> dict[str, Any]:
    """Note a round stopped by a handler: its work checks before each claim and call."""
    return {"round_id": round_id, "accepted": True}
