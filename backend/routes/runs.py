"""Running the UnderCover Agent: on one claim, or on the whole queue."""

import json
import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from agent import claim as agent
from backend import db
from backend.db import Db
from backend.rules import find_claim

logger = logging.getLogger(__name__)
queue_lock = threading.Lock()
queue_run: dict[str, Any] = {
    "running": False,
    "claim_ids": [],
    "done": 0,
    "current": None,
}

router = APIRouter(prefix="/api")


def thread_id_for(claim_id: str) -> str:
    """Return a new thread id for a run of the agent on a claim."""
    return f"{claim_id}-{uuid.uuid4().hex[:8]}"


@router.post("/claims/{claim_id}/run", operation_id="run_claim")
def run_claim(
    claim_id: str, background_tasks: BackgroundTasks, conn: Db
) -> dict[str, str]:
    """Start the UnderCover Agent on a waiting claim."""
    if find_claim(conn, claim_id)["status"] != "waiting":
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    thread_id = thread_id_for(claim_id)
    background_tasks.add_task(agent.run, claim_id, thread_id)
    return {"claim_id": claim_id, "thread_id": thread_id}


def work_through(claim_ids: list[str]) -> None:
    """Run the agent on each claim in turn, skipping any no longer waiting."""
    try:
        for claim_id in claim_ids:
            queue_run["current"] = claim_id
            conn = db.connect()
            status = find_claim(conn, claim_id)["status"]
            conn.close()
            if status == "waiting":
                try:
                    agent.run(claim_id, thread_id_for(claim_id))
                except Exception:
                    logger.exception("The agent's run on %s failed", claim_id)
            queue_run["done"] += 1
    finally:
        with queue_lock:
            queue_run.update(running=False, current=None)


@router.post("/queue/run", operation_id="run_queue")
def run_queue(background_tasks: BackgroundTasks, conn: Db) -> dict[str, Any]:
    """Start the UnderCover Agent on every waiting claim, one at a time."""
    rows = conn.execute("SELECT claim_id, body FROM claims WHERE status = 'waiting'")
    claims = sorted(
        (json.loads(row["body"])["submitted_on"], row["claim_id"]) for row in rows
    )
    with queue_lock:
        if queue_run["running"]:
            raise HTTPException(409, "The agent is already working through the queue")
        claim_ids = [claim_id for _, claim_id in claims]
        queue_run.update(running=True, claim_ids=claim_ids, done=0, current=None)
    background_tasks.add_task(work_through, claim_ids)
    return dict(queue_run)


@router.get("/queue/run", operation_id="get_queue_run")
def get_queue_run() -> dict[str, Any]:
    """Say whether the agent is working through the queue, and how far it has got."""
    return dict(queue_run)
