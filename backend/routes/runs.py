"""Running the UnderCover Agent: on one claim, or a run over the queue."""

import json
import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from agent import claim as agent
from agent import queue as queue_agent
from backend import db, runs
from backend.db import Db
from backend.rules import find_claim
from backend.schemas import Failure, RunStart, Summary, Todos

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


@router.post("/runs", operation_id="start_run")
def start_run(
    start: RunStart, background_tasks: BackgroundTasks, conn: Db
) -> dict[str, Any]:
    """Start the UnderCover Agent on the queue, working up to cap claims."""
    with conn:
        run_id = runs.start(conn, start.cap)
    background_tasks.add_task(queue_agent.run, run_id)
    return get_run(run_id, conn)


@router.get("/runs/current", operation_id="get_current_run")
def get_current_run(conn: Db) -> dict[str, Any] | None:
    """Get the latest queue run: its claims, its to-do list and its summary."""
    row = conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    return runs.describe(conn, row) if row else None


@router.get("/runs/{run_id}", operation_id="get_run")
def get_run(run_id: int, conn: Db) -> dict[str, Any]:
    """Get a queue run: its claims, its to-do list and its summary."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"No run {run_id}")
    return runs.describe(conn, row)


@router.put("/runs/{run_id}/todos", operation_id="write_todos")
def write_todos(run_id: int, todos: Todos, conn: Db) -> dict[str, Any]:
    """Store the agent's whole to-do list for a run."""
    runs.find_run(conn, run_id)
    with conn:
        conn.execute(
            "UPDATE runs SET todos = ? WHERE run_id = ?",
            (json.dumps([todo.model_dump() for todo in todos.todos]), run_id),
        )
    return {"run_id": run_id, "todos": len(todos.todos)}


@router.post("/runs/{run_id}/claims/{claim_id}", operation_id="take_claim")
def take_claim(run_id: int, claim_id: str, conn: Db) -> dict[str, Any]:
    """Add a waiting claim to a run, within its cap."""
    with conn:
        position = runs.take(conn, run_id, claim_id)
    return {"run_id": run_id, "claim_id": claim_id, "position": position}


@router.post("/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: int, summary: Summary, conn: Db) -> dict[str, Any]:
    """Finish a run with a summary, once no claim within its cap is waiting."""
    missed = runs.missed(conn, run_id)
    if missed:
        raise HTTPException(
            409, f"These claims are still waiting: {', '.join(missed)}. Work them first"
        )
    with conn:
        runs.end(conn, run_id, "finished", summary.summary)
    return get_run(run_id, conn)


@router.post("/runs/{run_id}/fail", operation_id="fail_run")
def fail_run(run_id: int, failure: Failure, conn: Db) -> dict[str, Any]:
    """End a run that broke, sending its unfinished claims back to the queue."""
    with conn:
        runs.end(conn, run_id, "failed", failure.reason)
    return get_run(run_id, conn)


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
    with queue_lock:
        if queue_run["running"]:
            raise HTTPException(409, "The agent is already working through the queue")
        claim_ids = runs.waiting(conn)
        queue_run.update(running=True, claim_ids=claim_ids, done=0, current=None)
    background_tasks.add_task(work_through, claim_ids)
    return dict(queue_run)


@router.get("/queue/run", operation_id="get_queue_run")
def get_queue_run() -> dict[str, Any]:
    """Say whether the agent is working through the queue, and how far it has got."""
    return dict(queue_run)
