"""The agent's service, its entry point: uv run -m uvicorn agent.service:app."""

import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from agent import claim, client, graph, queue, tracing

BACKEND_WAIT_TRIES = 30
BACKEND_WAIT_SECONDS = 1.0


class ClaimRun(BaseModel):
    """The thread to start a claim on."""

    thread_id: str


def signed_off_claims() -> list[str]:
    """Return the claims signed off while the agent was away, once the backend is up."""
    for _ in range(BACKEND_WAIT_TRIES):
        try:
            with client.backend() as backend:
                claims = backend.get("/api/claims").raise_for_status().json()
        except httpx.HTTPError:
            time.sleep(BACKEND_WAIT_SECONDS)
            continue
        return [
            found["claim_id"]
            for found in claims
            if found["status"] == "in_progress" and found["signed_off"]
        ]
    return []


def pick_up_signed_off() -> None:
    """Pay what was signed off while the agent was away, and warm up for the next."""
    claims = signed_off_claims()
    config = tracing.config("warm-up", graph.RECURSION_LIMIT)
    claim.build(None).get_state(config)
    for claim_id in claims:
        claim.carry_on(claim_id)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Pick up signed-off claims in the background, so startup doesn't wait for them."""
    threading.Thread(target=pick_up_signed_off, daemon=True).start()
    yield


app = FastAPI(title="UnderCover Agent", lifespan=lifespan)


@app.get("/health", operation_id="agent_health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}


@app.post("/claims/{claim_id}/resume", operation_id="resume_claim")
def resume_claim(claim_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Pick a signed-off claim back up from where it stopped."""
    background_tasks.add_task(claim.carry_on, claim_id)
    return {"claim_id": claim_id, "accepted": True}


@app.post("/claims/{claim_id}/run", operation_id="work_claim")
def work_claim(
    claim_id: str, start: ClaimRun, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Start the agent on one waiting claim."""
    background_tasks.add_task(claim.run, claim_id, start.thread_id)
    return {"claim_id": claim_id, "accepted": True}


@app.post("/runs/{run_id}", operation_id="work_run")
def work_run(run_id: int, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Start the agent on a queue run, carrying on what was stopped first."""
    background_tasks.add_task(queue.run, run_id)
    return {"run_id": run_id, "accepted": True}
