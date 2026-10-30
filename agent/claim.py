"""The claim agent: decides one claim from a clean start and reports back in a line."""

from typing import Any

import httpx
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel

from agent import client, tracing
from agent.middleware import StepRecorder
from agent.model import model
from agent.tools import TOOLS

MODEL_CALLS = 30
RETRIES = 2
RETRY_DELAY = 1.0
RECURSION_LIMIT = 300


def report(claim: dict[str, Any]) -> str:
    """Describe where a claim ended up, in one line."""
    decision = claim["decision"]
    if decision is None:
        return f"{claim['claim_id']}: no decision, now {claim['status']}"
    line = f"{claim['claim_id']}: {decision['decision']} ${decision['payout']:,.2f}"
    if claim["status"] == "awaiting_sign_off":
        line += ", waiting for a handler's sign-off"
    return line


def fail(backend: httpx.Client, claim_id: str, reason: str) -> str:
    """Count a failed attempt and say where the claim goes next."""
    status = backend.post(
        f"/api/claims/{claim_id}/fail", json={"reason": reason}
    ).json()["status"]
    where = "back in the queue" if status == "waiting" else "left for a handler"
    return f"{claim_id}: failed ({reason}), {where}"


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Work one claim and report back in a line: the decision, or what went wrong."""
    with client.backend() as backend:
        started = backend.post(
            f"/api/claims/{claim_id}/start", json={"thread_id": thread_id}
        )
        if not started.is_success:
            return f"{claim_id}: not started, {client.reply(started)}"
        instructions = backend.get("/api/instructions").json()["claim"]
        middleware: list[AgentMiddleware[Any, Any, Any]] = [
            ModelRetryMiddleware(
                max_retries=RETRIES, on_failure="error", initial_delay=RETRY_DELAY
            ),
            ModelCallLimitMiddleware(run_limit=MODEL_CALLS, exit_behavior="error"),
            StepRecorder(backend, claim_id),
        ]
        agent = create_agent(
            llm or model(),
            tools=TOOLS,
            system_prompt=instructions,
            middleware=middleware,
        )
        try:
            agent.invoke(
                {
                    "messages": [
                        {"role": "user", "content": f"Decide claim {claim_id}."}
                    ]
                },
                config=tracing.config(thread_id, RECURSION_LIMIT),
            )
        except Exception as error:
            return fail(backend, claim_id, f"The agent's run failed: {error}")
        finally:
            tracing.flush()
        claim = backend.get(f"/api/claims/{claim_id}").json()
        if claim["status"] == "in_progress" and claim["decision"] is None:
            return fail(
                backend, claim_id, "The agent finished without recording a decision"
            )
    return report(claim)
