"""The claim agent's graph: its state, nodes and edges, saved after every step."""

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command, RetryPolicy, interrupt

from agent import client
from agent.tools import TOOLS

MODEL_CALLS = 30
RETRIES = 2
RETRY_DELAY = 1.0
RECURSION_LIMIT = 3 * MODEL_CALLS + 20
STEP_LENGTH = 600


class ClaimState(TypedDict):
    """What the graph keeps for one claim."""

    messages: Annotated[list[AnyMessage], add_messages]
    claim_id: str
    thread_id: str
    model_calls: int
    signed_off_by: str


class TooManyModelCalls(Exception):
    """The agent has used all its model calls on this claim."""


def record_step(claim_id: str, kind: str, text: str, key: str) -> None:
    """Record one step on the claim; the key means a repeat is ignored."""
    with client.backend() as backend:
        backend.post(
            f"/api/claims/{claim_id}/steps",
            json={"kind": kind, "text": text, "key": key},
        )


def standing(claim_id: str) -> dict[str, Any]:
    """Ask the backend where the claim stands."""
    with client.backend() as backend:
        return backend.get(f"/api/claims/{claim_id}/standing").json()


def report(claim: dict[str, Any]) -> str:
    """Describe where a claim ended up, in one line."""
    decision = claim["decision"]
    if decision is None:
        return f"{claim['claim_id']}: no decision, now {claim['status']}"
    line = f"{claim['claim_id']}: {decision['decision']} ${decision['payout']:,.2f}"
    if claim["status"] == "awaiting_sign_off":
        line += ", waiting for a handler's sign-off"
    return line


def retry_model(error: Exception) -> bool:
    """Retry a provider's errors, but not the limit on model calls."""
    return not isinstance(error, TooManyModelCalls)


def record_tool_result(
    request: ToolCallRequest, execute: Callable[[ToolCallRequest], Any]
) -> ToolMessage | Command[Any]:
    """Run one tool and record its result; a section read is recorded as a read."""
    result = execute(request)
    if isinstance(result, ToolMessage):
        state: Any = request.state
        message = state["messages"][-1]
        name = request.tool_call["name"]
        number = [call["id"] for call in message.tool_calls].index(
            request.tool_call["id"]
        )
        kind, text = (
            ("read", result.text.splitlines()[0])
            if name == "read_section" and not result.text.startswith("Refused")
            else ("tool_result", f"{name}: {result.text[:STEP_LENGTH]}")
        )
        key = f"{state['thread_id']}:{message.id}:{number}:result"
        record_step(state["claim_id"], kind, text, key)
    return result


def record(state: ClaimState) -> dict[str, Any]:
    """Record the model's saved reply: its tool calls, or its answer."""
    message: Any = state["messages"][-1]
    prefix = f"{state['thread_id']}:{message.id}"
    if not message.tool_calls:
        record_step(state["claim_id"], "answer", message.text, f"{prefix}:answer")
    for number, call in enumerate(message.tool_calls):
        args = json.dumps(call["args"], ensure_ascii=False)
        record_step(
            state["claim_id"],
            "tool_call",
            f"{call['name']} {args}",
            f"{prefix}:{number}:call",
        )
    return {}


def after_record(state: ClaimState) -> str:
    """Run the tools the model asked for; an answer with no tools ends the work."""
    message: Any = state["messages"][-1]
    return "tools" if message.tool_calls else END


def after_tools(state: ClaimState) -> Literal["agent", "sign_off", "pay", "close"]:
    """Ask the backend where the claim stands; it alone applies the limit."""
    claim = standing(state["claim_id"])
    if claim["decision"] is None:
        return "agent"
    if claim["status"] == "awaiting_sign_off":
        return "sign_off"
    if claim["status"] == "in_progress":
        return "pay"
    return "close"


def sign_off(state: ClaimState) -> dict[str, Any]:
    """Wait for a handler. Nothing else here: this runs again on resume."""
    answer = interrupt({"claim_id": state["claim_id"]})
    return {"signed_off_by": answer["handler_id"]}


def pay(state: ClaimState) -> dict[str, Any]:
    """Pay the approved payout. The backend refuses it without a sign-off."""
    claim_id = state["claim_id"]
    amount = standing(claim_id)["decision"]["payout"]
    prefix = f"{state['thread_id']}:pay"
    call = f"pay_claim {json.dumps({'amount': amount})}"
    record_step(claim_id, "tool_call", call, f"{prefix}:call")
    with client.backend() as backend:
        response = backend.post(
            f"/api/claims/{claim_id}/payment", json={"amount": amount}
        )
    if not response.is_success:
        raise RuntimeError(client.reply(response))
    result = f"pay_claim: Paid ${amount:,.2f}"
    record_step(claim_id, "tool_result", result, f"{prefix}:result")
    return {}


def close(state: ClaimState) -> dict[str, Any]:
    """Record where the claim ended up, as the agent's answer."""
    line = report(standing(state["claim_id"]))
    record_step(state["claim_id"], "answer", line, f"{state['thread_id']}:close")
    return {}


def agent_node(llm: BaseChatModel, instructions: str) -> Any:
    """Make the node that calls the model with the conversation so far."""
    bound = llm.bind_tools(TOOLS)
    system = SystemMessage(instructions)

    def agent(state: ClaimState) -> dict[str, Any]:
        calls = state["model_calls"]
        if calls >= MODEL_CALLS:
            raise TooManyModelCalls(f"Stopped after {MODEL_CALLS} model calls")
        reply = bound.invoke([system, *state["messages"]])
        return {"messages": [reply], "model_calls": calls + 1}

    return agent


def build(
    llm: BaseChatModel, instructions: str, saver: BaseCheckpointSaver[Any]
) -> Any:
    """Build the claim graph on this model and checkpointer."""
    retry = RetryPolicy(
        max_attempts=RETRIES + 1,
        initial_interval=RETRY_DELAY,
        jitter=False,
        retry_on=retry_model,
    )
    builder = StateGraph(ClaimState)
    builder.add_node("agent", agent_node(llm, instructions), retry_policy=retry)
    builder.add_node("record", record)
    builder.add_node("tools", ToolNode(TOOLS, wrap_tool_call=record_tool_result))
    builder.add_node("sign_off", sign_off)
    builder.add_node("pay", pay)
    builder.add_node("close", close)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", "record")
    builder.add_conditional_edges("record", after_record, ["tools", END])
    builder.add_conditional_edges(
        "tools", after_tools, ["agent", "sign_off", "pay", "close"]
    )
    builder.add_edge("sign_off", "pay")
    builder.add_edge("pay", "close")
    builder.add_edge("close", END)
    return builder.compile(checkpointer=saver)
