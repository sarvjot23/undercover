"""The queue agent: plans a run as a to-do list and hands each claim to a subagent."""

import json
import uuid
from collections.abc import Callable
from typing import Any, Literal

import httpx
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel

from agent import claim, client, graph, lease
from agent.model import model

ClaimModels = Callable[[str], BaseChatModel | None]


class Todo(BaseModel):
    """One item on the to-do list: a claim, a short note and where it stands."""

    claim_id: str
    note: str
    status: Literal["to_do", "in_progress", "done", "left_for_handler"]


def tools(backend: httpx.Client, run_id: int, models: ClaimModels) -> list[BaseTool]:
    """The queue agent's tools for one run."""

    @tool
    def list_waiting_claims() -> str:
        """List the waiting claims: id, type, amount claimed and date submitted."""
        claims = backend.get("/api/claims").json()
        return "\n".join(
            f"{c['claim_id']} {c['claim_type']} ${c['amount_claimed']:,.2f} "
            f"submitted {c['submitted_on']}"
            for c in claims
            if c["status"] == "waiting"
        )

    @tool
    def write_todos(todos: list[Todo]) -> str:
        """Write the whole to-do list for this run, replacing the last one."""
        response = backend.put(
            f"/api/runs/{run_id}/todos",
            json={"todos": [todo.model_dump() for todo in todos]},
        )
        return client.reply(response)

    @tool
    def work_claim(claim_id: str) -> str:
        """Hand a waiting claim to a claim handler, who decides it and reports back."""
        taken = backend.post(f"/api/runs/{run_id}/claims/{claim_id}")
        if not taken.is_success:
            return client.reply(taken)
        thread_id = f"{claim_id}-{uuid.uuid4().hex[:8]}"
        return claim.run(claim_id, thread_id, models(claim_id))

    @tool
    def finish_run(summary: str) -> str:
        """Finish the run with a short summary for the handlers."""
        response = backend.post(f"/api/runs/{run_id}/finish", json={"summary": summary})
        return "Finished." if response.is_success else client.reply(response)

    return [list_waiting_claims, write_todos, work_claim, finish_run]


def carry_on(backend: httpx.Client, models: ClaimModels) -> list[str]:
    """Pick up every claim that was stopped or signed off, and report each in a line."""
    claims = backend.get("/api/claims").json()
    return [
        claim.carry_on(found["claim_id"], models(found["claim_id"]))
        for found in claims
        if found["status"] == "in_progress" and found["thread_id"]
    ]


def task_for(found: dict[str, Any], carried_on: list[str]) -> str:
    """Tell the queue agent what to do, and what happened if this run stopped before."""
    task = f"Work the queue. This run may work up to {found['cap']} claims."
    if found["todos"]:
        task += (
            " This run stopped partway and you are finishing it. "
            f"Your to-do list so far: {json.dumps(found['todos'])}. "
            f"You have already taken: {', '.join(found['claim_ids'])}."
        )
    if carried_on:
        task += " These claims have just been carried on: " + "; ".join(carried_on)
    return task


def run(
    run_id: int,
    llm: BaseChatModel | None = None,
    models: ClaimModels = lambda _: None,
) -> str:
    """Work the queue for one run, holding its lease, and return where it ended."""
    with lease.holding(f"/api/runs/{run_id}/lease") as held:
        if not held:
            return f"Run {run_id}: another worker is on it"
        return work_run(run_id, llm, models)


def work_run(run_id: int, llm: BaseChatModel | None, models: ClaimModels) -> str:
    """Carry on what was stopped, then have the queue agent work the rest."""
    with client.backend() as backend:
        carried_on = carry_on(backend, models)
        found = backend.get(f"/api/runs/{run_id}").json()
        instructions = backend.get("/api/instructions").json()["queue"]
        calls = 4 * found["total"] + 10
        middleware: list[AgentMiddleware[Any, Any, Any]] = [
            ModelRetryMiddleware(
                max_retries=graph.RETRIES,
                on_failure="error",
                initial_delay=graph.RETRY_DELAY,
            ),
            ModelCallLimitMiddleware(run_limit=calls, exit_behavior="error"),
        ]
        agent = create_agent(
            llm or model(),
            tools=tools(backend, run_id, models),
            system_prompt=instructions,
            middleware=middleware,
        )
        task = task_for(found, carried_on)
        try:
            agent.invoke(
                {"messages": [{"role": "user", "content": task}]},
                config={
                    "configurable": {"thread_id": f"run-{run_id}"},
                    "recursion_limit": 2 * calls + 10,
                },
            )
        except Exception as error:
            reason = f"The queue agent's run failed: {error}"
            backend.post(f"/api/runs/{run_id}/fail", json={"reason": reason})
        if backend.get(f"/api/runs/{run_id}").json()["status"] == "running":
            reason = "The queue agent stopped without finishing the run"
            backend.post(f"/api/runs/{run_id}/fail", json={"reason": reason})
        ended = backend.get(f"/api/runs/{run_id}").json()
    return f"Run {run_id} {ended['status']}: {ended['summary']}"
