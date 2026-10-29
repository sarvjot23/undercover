"""The claim agent: decides one claim, posting each step to the backend."""

import json
from typing import Any

import httpx
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agent import client
from agent.model import model
from agent.tools import TOOLS

STEP_LENGTH = 600


def steps(message: BaseMessage) -> list[tuple[str, str]]:
    """Describe one message from the agent as steps for the dashboard."""
    if isinstance(message, ToolMessage):
        return [("tool_result", f"{message.name}: {message.text[:STEP_LENGTH]}")]
    if isinstance(message, AIMessage) and message.tool_calls:
        return [
            ("tool_call", f"{call['name']} {json.dumps(call['args'])}")
            for call in message.tool_calls
        ]
    return [("answer", message.text)]


def work(agent: Any, backend: httpx.Client, claim_id: str, thread_id: str) -> str:
    """Run the agent on a claim, posting each step to the backend."""
    answer = ""
    updates = agent.stream(
        {"messages": [{"role": "user", "content": f"Decide claim {claim_id}."}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    )
    for update in updates:
        for node in update.values():
            for message in node["messages"]:
                for kind, text in steps(message):
                    backend.post(
                        f"/api/claims/{claim_id}/steps",
                        json={"kind": kind, "text": text},
                    )
                    if kind == "answer":
                        answer = text
    return answer


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the agent on one claim and return its final reply."""
    with client.backend() as backend:
        backend.post(f"/api/claims/{claim_id}/start").raise_for_status()
        instructions = backend.get("/api/instructions").json()["text"]
        agent = create_agent(llm or model(), tools=TOOLS, system_prompt=instructions)
        try:
            answer = work(agent, backend, claim_id, thread_id)
        except Exception as error:
            backend.post(
                f"/api/claims/{claim_id}/fail",
                json={"reason": f"The agent's run failed: {error}"},
            )
            raise
        if backend.get(f"/api/claims/{claim_id}").json()["status"] == "in_progress":
            backend.post(
                f"/api/claims/{claim_id}/fail",
                json={"reason": "The agent finished without recording a decision"},
            )
    return answer
