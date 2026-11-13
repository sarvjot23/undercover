"""The claim agent's graph: its state, nodes and edges, saved after every step."""

import json
import logging
from collections.abc import Callable
from functools import cache
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command, RetryPolicy, interrupt

from agent import client, memory, screening, steps, tools
from agent.direct import APP
from agent.mcp_bridge import Refused
from agent.tools import ClaimContext

MODEL_CALLS = 30
RETRIES = 2
RETRY_DELAY = 1.0
RECURSION_LIMIT = 3 * MODEL_CALLS + 20
STEP_LENGTH = steps.STEP_LENGTH
# The dispatcher waits these out and carries the claim on, so the graph doesn't retry.
PASSED_UP = (ModelRateLimitError, ModelTimeoutError)
After = Literal["pay", "close"]
log = logging.getLogger(__name__)


class ClaimState(TypedDict):
    """What the graph keeps for one claim."""

    messages: Annotated[list[AnyMessage], add_messages]
    claim_id: str
    thread_id: str
    model_calls: int
    signed_off_by: str
    # Whether this decision is saved to memory, so it's saved once.
    remembered: bool


class TooManyModelCalls(Exception):
    """The agent has used all its model calls on this claim."""


def record_step(
    claim_id: str, kind: str, text: str, key: str, detail: Any = None
) -> None:
    """Record one step on the claim; the key means a repeat is ignored."""
    with client.backend() as backend:
        backend.post(
            f"/api/claims/{claim_id}/steps",
            json={"kind": kind, "text": text, "key": key, "detail": detail},
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
    """Retry a provider's errors, but not the limit, rate limits or timeouts."""
    return not isinstance(error, (TooManyModelCalls, *PASSED_UP))


def record_usage(claim_id: str, run_id: int | None, reply: AIMessage) -> None:
    """Record a reply's tokens and cost, as OpenRouter reports them, once per reply."""
    usage = reply.response_metadata.get("token_usage")
    if not usage:
        return
    with client.backend() as backend:
        backend.post(
            f"/api/claims/{claim_id}/usage",
            json={
                "run_id": run_id,
                "model": reply.response_metadata["model_name"],
                "input_tokens": usage["prompt_tokens"],
                "output_tokens": usage["completion_tokens"],
                "cost": usage.get("cost", 0.0),
                "key": reply.id,
            },
        )


def check(state: ClaimState, config: RunnableConfig) -> dict[str, Any]:
    """Run the security check before the claim agent's model sees the claim.

    A claim that tries to instruct its handler is referred, with the check's reason.
    """
    claim_id = state["claim_id"]
    run_id = config.get("configurable", {})["run_id"]
    with client.backend() as backend:
        claim = backend.get(f"/api/claims/{claim_id}").json()
    found = screening.screen(claim, lambda reply: record_usage(claim_id, run_id, reply))
    result = (
        "Instructions found" if found.instructions_found else "No instructions found"
    )
    record_step(
        claim_id, "check", f"{result}: {found.reason}", f"{state['thread_id']}:check"
    )
    if found.instructions_found:
        with client.backend() as backend:
            backend.post(
                f"/api/claims/{claim_id}/decision",
                json={
                    "decision": "refer",
                    "payout": 0,
                    "reasons": f"{screening.REFERRAL} {found.reason}",
                    "policy_section": screening.SECTION,
                    "decided_by": screening.MAKER,
                },
            ).raise_for_status()
    return {}


def after_check(state: ClaimState) -> Literal["agent", "close"]:
    """On to the claim agent, unless the check referred the claim."""
    return "agent" if standing(state["claim_id"])["decision"] is None else "close"


def tool_result_recorder(claim: ClaimContext) -> Any:
    """Make the wrapper that runs one tool and records its result as a step: a
    lookup, a memory search, a refusal or a plain result."""

    def record_tool_result(
        request: ToolCallRequest, execute: Callable[[ToolCallRequest], Any]
    ) -> ToolMessage | Command[Any]:
        result = execute(request)
        if isinstance(result, ToolMessage):
            state: Any = request.state
            message = state["messages"][-1]
            call = request.tool_call
            number = [made["id"] for made in message.tool_calls].index(call["id"])
            name = call["name"]
            kind, text, detail = steps.describe(
                name, tools.routed_name(claim, name), call["args"], result.text
            )
            key = f"{state['thread_id']}:{message.id}:{number}:result"
            record_step(state["claim_id"], kind, text, key, detail)
        return result

    return record_tool_result


def record_node(claim: ClaimContext) -> Any:
    """Make the node that records the model's saved reply: its tool calls, named as
    the claim's route names them, or its answer."""

    def record(state: ClaimState) -> dict[str, Any]:
        message: Any = state["messages"][-1]
        prefix = f"{state['thread_id']}:{message.id}"
        if not message.tool_calls:
            record_step(state["claim_id"], "answer", message.text, f"{prefix}:answer")
        for number, call in enumerate(message.tool_calls):
            args = json.dumps(call["args"], ensure_ascii=False)
            record_step(
                state["claim_id"],
                "tool_call",
                f"{tools.routed_name(claim, call['name'])} {args}",
                f"{prefix}:{number}:call",
            )
        return {}

    return record


def after_record(state: ClaimState) -> str:
    """Run the tools the model asked for; an answer with no tools ends the work."""
    message: Any = state["messages"][-1]
    return "tools" if message.tool_calls else END


def waits_for_sign_off(found: dict[str, Any]) -> bool:
    """Whether a claim pauses for a handler: never an evaluation's copy, which
    nobody signs off."""
    return found["status"] == "awaiting_sign_off" and found["evaluation_id"] is None


def after_tools(state: ClaimState) -> Literal["agent", "sign_off", "remember"]:
    """Back to the model until it has recorded a decision; the backend alone applies
    the limit, and an approval over it pauses before anything else."""
    found = standing(state["claim_id"])
    if found["decision"] is None:
        return "agent"
    return "sign_off" if waits_for_sign_off(found) else "remember"


def after_decision(claim: dict[str, Any]) -> After:
    """Where a remembered claim goes: an approval within the limit is paid."""
    return "pay" if claim["status"] == "in_progress" else "close"


def remember_node(claim: ClaimContext) -> Any:
    """Make the node that saves the claim and the decision the agent recorded to the
    customer's memory, in code every time. It runs once for each decision: after
    the decision, or after the sign-off when it waited for one.

    Nothing is saved without memory, in an evaluation or for an evaluation's copy.
    The check's referrals never come this way. If AgentCore can't be reached, the
    claim keeps its decision.
    """

    def remember(state: ClaimState) -> Command[After]:
        claim_id = state["claim_id"]
        found = standing(claim_id)
        due = not state.get("remembered") and found["evaluation_id"] is None
        if claim.memory is not None and due:
            with client.backend() as backend:
                full = backend.get(f"/api/claims/{claim_id}").json()
            try:
                saved = memory.save(claim.memory, full)
            except Exception as error:  # noqa: BLE001 - the decision stands
                log.warning("Couldn't save %s to memory: %s", claim_id, error)
            else:
                key = f"{state['thread_id']}:remember"
                record_step(claim_id, "memory_save", saved[:STEP_LENGTH], key)
        return Command(goto=after_decision(found), update={"remembered": True})

    return remember


def sign_off(state: ClaimState) -> Command[Literal["remember", "agent"]]:
    """Wait for a handler. A sign-off pays the claim, so the work goes on to remember
    it. A decision sent back goes back to the model with the handler's note and a
    full allowance of model calls; the app has already withdrawn the decision, so
    nothing can pay it.

    LangGraph runs this node again from the top on a resume, so nothing goes before
    the interrupt.
    """
    answer = interrupt({"claim_id": state["claim_id"]})
    if "signed_off_by" in answer:
        update = {"signed_off_by": answer["signed_off_by"]}
        return Command(goto="remember", update=update)
    return Command(
        goto="agent",
        update={
            "messages": [HumanMessage(answer["message"])],
            "model_calls": 0,
            "remembered": False,
        },
    )


def hold(claim_id: str, reason: str) -> None:
    """Have the claim wait for a handler's sign-off, since the Gateway refused it."""
    with client.backend() as backend:
        backend.post(
            f"/api/claims/{claim_id}/hold", json={"reason": reason}
        ).raise_for_status()


def pay_node(claim: ClaimContext) -> Any:
    """Make the node that pays the approved payout, on the claim's route.

    The app refuses it without a sign-off. A payment the Gateway refuses waits for a
    handler's sign-off, as an approval over the limit does, so a handler can pay it.
    """

    def pay(state: ClaimState) -> Command[Literal["sign_off", "close"]]:
        claim_id = state["claim_id"]
        amount = standing(claim_id)["decision"]["payout"]
        key = f"{state['thread_id']}:pay:result"
        name = claim.route.tool_name(APP, "pay_claim")
        try:
            claim.route.call(APP, "pay_claim", {"claim_id": claim_id, "amount": amount})
        except Refused as refused:
            if refused.by != "the Gateway":
                raise RuntimeError(str(refused)) from refused
            by = {"by": refused.by}
            record_step(claim_id, "refusal", f"{name}: {refused}", key, by)
            hold(claim_id, refused.reason)
            held = waits_for_sign_off(standing(claim_id))
            return Command(goto="sign_off" if held else "close")
        record_step(claim_id, "tool_result", f"{name}: Paid ${amount:,.2f}", key)
        return Command(goto="close")

    return pay


def close(state: ClaimState) -> dict[str, Any]:
    """Record where the claim ended up, as the agent's answer."""
    line = report(standing(state["claim_id"]))
    record_step(state["claim_id"], "answer", line, f"{state['thread_id']}:close")
    return {}


def agent_node(
    make_llm: Callable[[], BaseChatModel], instructions: str, bound_tools: list[Any]
) -> Any:
    """Make the node that calls the model with the conversation so far.

    The model is made on first use: paying a signed-off claim doesn't need one.
    """
    system = SystemMessage(instructions)

    @cache
    def bound() -> Any:
        return make_llm().bind_tools(bound_tools)

    def agent(state: ClaimState, config: RunnableConfig) -> dict[str, Any]:
        calls = state["model_calls"]
        if calls >= MODEL_CALLS:
            raise TooManyModelCalls(f"Stopped after {MODEL_CALLS} model calls")
        reply = bound().invoke([system, *state["messages"]])
        run_id = config.get("configurable", {})["run_id"]
        record_usage(state["claim_id"], run_id, reply)
        return {"messages": [reply], "model_calls": calls + 1}

    return agent


def build(
    make_llm: Callable[[], BaseChatModel],
    instructions: str,
    saver: BaseCheckpointSaver[Any],
    claim: ClaimContext,
) -> Any:
    """Build the claim graph for one claim on this model and checkpointer."""
    claim_tools = tools.for_claim(claim)
    retry = RetryPolicy(
        max_attempts=RETRIES + 1,
        initial_interval=RETRY_DELAY,
        jitter=False,
        retry_on=retry_model,
    )
    builder = StateGraph(ClaimState)
    builder.add_node("check", check)
    builder.add_node(
        "agent", agent_node(make_llm, instructions, claim_tools), retry_policy=retry
    )
    builder.add_node("record", record_node(claim))
    builder.add_node(
        "tools", ToolNode(claim_tools, wrap_tool_call=tool_result_recorder(claim))
    )
    builder.add_node("remember", remember_node(claim), destinations=("pay", "close"))
    builder.add_node("sign_off", sign_off, destinations=("remember", "agent"))
    builder.add_node("pay", pay_node(claim), destinations=("sign_off", "close"))
    builder.add_node("close", close)
    builder.add_edge(START, "check")
    builder.add_conditional_edges("check", after_check, ["agent", "close"])
    builder.add_edge("agent", "record")
    builder.add_conditional_edges("record", after_record, ["tools", END])
    builder.add_conditional_edges(
        "tools", after_tools, ["agent", "sign_off", "remember"]
    )
    builder.add_edge("close", END)
    return builder.compile(checkpointer=saver, store=claim.memory)
