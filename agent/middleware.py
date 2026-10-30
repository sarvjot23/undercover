"""Middleware for the claim agent: every step it takes is recorded on the claim."""

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

STEP_LENGTH = 600


class StepRecorder(AgentMiddleware):
    """Post each tool call, tool result, section read and answer to the claim."""

    def __init__(self, backend: httpx.Client, claim_id: str) -> None:
        super().__init__()
        self.backend = backend
        self.claim_id = claim_id

    def record(self, kind: str, text: str) -> None:
        """Record one step on the claim."""
        self.backend.post(
            f"/api/claims/{self.claim_id}/steps",
            json={"kind": kind, "text": text, "key": uuid.uuid4().hex},
        )

    def after_model(self, state: Any, runtime: Any) -> None:
        """Record the model's tool calls, or its answer."""
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            return
        if not message.tool_calls:
            self.record("answer", message.text)
        for call in message.tool_calls:
            self.record(
                "tool_call",
                f"{call['name']} {json.dumps(call['args'], ensure_ascii=False)}",
            )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Record what a tool returned; a section read is recorded as a read."""
        result = handler(request)
        if isinstance(result, ToolMessage):
            name = request.tool_call["name"]
            if name == "read_section" and not result.text.startswith("Refused"):
                self.record("read", result.text.splitlines()[0])
            else:
                self.record("tool_result", f"{name}: {result.text[:STEP_LENGTH]}")
        return result
