"""The agent's service, its entry point: uv run -m uvicorn agent.service:app."""

import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import claim, client, dispatcher, graph, model, tracing

BACKEND_WAIT_TRIES = 30
BACKEND_WAIT_SECONDS = 1.0
MAX_AGENTS = 25
ALREADY_RUNNING = "A dispatch or evaluation is already running"

# Held while a dispatch or an evaluation is being worked: one run at a time.
busy = threading.Lock()


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


def pick_up_signed_off() -> None:
    """Stop what was left running, pay what was signed off, and warm up for the next.

    The queue leaves out evaluation copies, so none is ever picked up here.
    """
    claims = backend_claims()
    if not claims:
        return
    stop_leftover_run()
    config = tracing.config("warm-up", graph.RECURSION_LIMIT, None)
    claim.build(None).get_state(config)
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
        dispatcher.dispatch({"run_id": created["run_id"], "kind": record["kind"]}, n)
    finally:
        busy.release()


def start(
    record: dict[str, Any], n: int, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Take on a run at once and work it in the background, or refuse with a 409."""
    if not busy.acquire(blocking=False):
        raise HTTPException(409, ALREADY_RUNNING)
    background_tasks.add_task(work_run, {**record, "n": n, **model.describe()}, n)
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
