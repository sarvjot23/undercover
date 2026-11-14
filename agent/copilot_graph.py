"""The Copilot's graph: a turn of a conversation, saved after every step.

start -> recall -> model, then model -> tools -> model until the model answers, and
remember at the end. A sign-off goes tools -> confirm, which pauses with interrupt()
before anything else, so running it again on a resume repeats nothing.

The handler's sign-in is in the graph's context, given with each run, and never in
its state or config, which the checkpointer saves.
"""

import json
import os
import time
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from agent import checkpoints, copilot_client, memory, model, steps
from agent.copilot_client import Refused
from agent.copilot_tools import ACTIONS, KINDS, RECORDS, CopilotContext, context_tools
from agent.copilot_waiting import (
    check_success_criteria,
    wait_for_work,
    what_needs_me,
)

MODEL_CALLS = 25
RECURSION_LIMIT = 3 * MODEL_CALLS + 20
ANSWER_LENGTH = 2000
INSTRUCTIONS = Path(__file__).with_name("copilot.md")
STOPPED_PARTWAY = "This step stopped partway, before it finished."
TOO_MANY_CALLS = (
    f"I've used the {MODEL_CALLS} model calls I have for one question, so I've "
    "stopped here. Ask me again, perhaps in smaller steps."
)


class CopilotState(TypedDict):
    """What the graph keeps for a conversation: never the sign-in."""

    messages: Annotated[list[AnyMessage], add_messages]
    # The handler's message, which start puts into the conversation.
    asked: str
    # What memory found for this turn, for the model's instructions.
    remembered: list[str]
    model_calls: int
    cost: float
    # The card a sign-off waits on, read from our records.
    confirmation: dict[str, Any] | None


def instructions() -> str:
    """The Copilot's instructions, written as goals."""
    return INSTRUCTIONS.read_text(encoding="utf-8")


def turn_path(context: CopilotContext) -> str:
    """The app's address for this turn."""
    return f"/api/conversations/{context.conversation_id}/turns/{context.turn_id}"


def record_card(context: CopilotContext, key: str, card: dict[str, Any]) -> None:
    """Record a card the sidebar shows, as the handler, once by its key."""
    copilot_client.call(context.token, "PUT", f"{turn_path(context)}/steps/{key}", card)


def card(
    kind: str,
    tool: str,
    shown: str,
    asked: str,
    state: str = "working",
    **found: Any,
) -> dict[str, Any]:
    """A card as the app keeps it."""
    return {
        "kind": kind,
        "tool": tool,
        "input": shown,
        "state": state,
        "seconds": found.get("seconds", 0.0),
        "asked": asked,
        "answer": found.get("answer", "")[:ANSWER_LENGTH],
        "reason": found.get("reason", ""),
        "sources": found.get("sources", []),
    }


def unanswered(messages: list[AnyMessage]) -> list[ToolMessage]:
    """An answer for each tool call a stopped or failed turn left without one, so
    the model's history stays whole."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    return [
        ToolMessage(STOPPED_PARTWAY, tool_call_id=call["id"])
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
        if call["id"] not in answered
    ]


def start(state: CopilotState) -> dict[str, Any]:
    """Begin a turn: close what a stopped turn left open, then the handler's
    message, with the turn's count and cost from nothing."""
    return {
        "messages": [*unanswered(state["messages"]), HumanMessage(state["asked"])],
        "remembered": [],
        "model_calls": 0,
        "cost": 0.0,
        "confirmation": None,
    }


def recall(state: CopilotState, runtime: Runtime[CopilotContext]) -> dict[str, Any]:
    """Look up what the Copilot remembers about this handler that bears on their
    message, as a card like any other. With memory off it does nothing."""
    context = runtime.context
    if context.memory is None:
        return {}
    began = time.monotonic()
    handler_id = context.handler["handler_id"]
    found = memory.recall(context.memory, handler_id, state["asked"])
    record_card(
        context,
        "recall",
        card(
            "memory",
            "recall_memory",
            context.handler["name"],
            state["asked"],
            "done",
            seconds=round(time.monotonic() - began, 1),
            answer="\n".join(found) or "Nothing remembered yet.",
        ),
    )
    return {"remembered": found}


def who(context: CopilotContext, remembered: list[str]) -> str:
    """Who the Copilot works for on this turn, and what it remembers of them."""
    handler = context.handler
    may = "can" if handler["can_approve_over_limit"] else "can't"
    lines = [
        "## This turn",
        f"You work for {handler['name']} ({handler['role']}, {handler['handler_id']}),"
        f" who {may} sign off payouts over the approval limit.",
    ]
    if remembered:
        lines.append("What you remember about them:")
        lines.extend(f"- {note}" for note in remembered)
    return "\n".join(lines)


def model_node(make_llm: Callable[[], BaseChatModel], tools: list[BaseTool]) -> Any:
    """Make the node that calls the model, at most 25 times a turn."""

    @cache
    def bound() -> Any:
        return make_llm().bind_tools(tools)

    def call_model(
        state: CopilotState, runtime: Runtime[CopilotContext]
    ) -> dict[str, Any]:
        if state["model_calls"] >= MODEL_CALLS:
            return {"messages": [AIMessage(TOO_MANY_CALLS)]}
        system = SystemMessage(
            f"{instructions()}\n\n{who(runtime.context, state['remembered'])}"
        )
        reply = bound().invoke([system, *state["messages"]])
        usage = reply.response_metadata.get("token_usage") or {}
        return {
            "messages": [reply],
            "model_calls": state["model_calls"] + 1,
            "cost": state["cost"] + (usage.get("cost") or 0.0),
        }

    return call_model


def shown_input(arguments: dict[str, Any]) -> str:
    """A tool call's main input for its card, such as CLM-1012."""
    values = [str(v) for v in arguments.values() if v is not None]
    return values[0][:80] if values else ""


def sources_of(name: str, text: str) -> list[dict[str, Any]]:
    """The files and owners a context-layer answer came from."""
    if name not in steps.LOOKUPS:
        return []
    try:
        return steps.files_of(json.loads(text))
    except (ValueError, KeyError, TypeError):
        return []


def result_text(result: ToolMessage | Command[Any]) -> str:
    """What a tool answered, as the card shows it."""
    if isinstance(result, ToolMessage):
        return result.text
    update: Any = result.update
    return update["messages"][0].text


def record_tool_call(
    request: ToolCallRequest, execute: Callable[[ToolCallRequest], Any]
) -> ToolMessage | Command[Any]:
    """Run one tool and show it as a card: working, then done, refused or failed,
    with its time."""
    context: CopilotContext = request.runtime.context  # type: ignore[union-attr]
    call = request.tool_call
    key = call["id"] or call["name"]
    name = call["name"]
    asked = json.dumps(call["args"], ensure_ascii=False)
    shown = shown_input(call["args"])
    kind = KINDS.get(name, "context")
    record_card(context, key, card(kind, name, shown, asked))
    began = time.monotonic()
    try:
        result = execute(request)
    except Exception as error:
        seconds = round(time.monotonic() - began, 1)
        failed = card(
            kind, name, shown, asked, "failed", seconds=seconds, reason=str(error)
        )
        record_card(context, key, failed)
        raise
    text = result_text(result)
    refused = text.startswith("Refused")
    record_card(
        context,
        key,
        card(
            kind,
            name,
            shown,
            asked,
            "refused" if refused else "done",
            seconds=round(time.monotonic() - began, 1),
            answer=text,
            reason=text if refused else "",
            sources=sources_of(name, text),
        ),
    )
    return result


def after_model(state: CopilotState) -> Literal["tools", "remember"]:
    """Run the tools the model asked for, or end the turn with its answer."""
    message: Any = state["messages"][-1]
    return "tools" if message.tool_calls else "remember"


def after_tools(state: CopilotState) -> Literal["confirm", "model"]:
    """Pause for the handler when a sign-off waits on their confirmation."""
    return "confirm" if state["confirmation"] else "model"


def signed_off(context: CopilotContext, claim: dict[str, Any]) -> str:
    """Sign off as the handler, which pays the claim, and show it as an action."""
    claim_id = claim["claim_id"]
    began = time.monotonic()
    try:
        paid = copilot_client.call(
            context.token, "POST", f"/api/claims/{claim_id}/sign-off"
        )
    except Refused as refused:
        outcome = card(
            "action",
            "sign_off",
            claim_id,
            claim_id,
            "refused",
            seconds=round(time.monotonic() - began, 1),
            reason=str(refused),
        )
        record_card(context, f"sign-off-{claim_id}", outcome)
        return f"The app refused the sign-off of {claim_id}: {refused}"
    amount = paid["payment"]["amount"]
    said = f"Signed off {claim_id} and paid ${amount:,.2f}"
    outcome = card(
        "action",
        "sign_off",
        claim_id,
        claim_id,
        "done",
        seconds=round(time.monotonic() - began, 1),
        answer=said,
    )
    record_card(context, f"sign-off-{claim_id}", outcome)
    return said


def confirm(state: CopilotState, runtime: Runtime[CopilotContext]) -> dict[str, Any]:
    """Wait for the handler's answer on the confirmation card, then sign off or not.

    The interrupt comes first: LangGraph runs this node again from the top when the
    handler answers, so nothing before it may do anything.
    """
    answer = interrupt(state["confirmation"])
    context = runtime.context
    claim: Any = state["confirmation"]
    name = context.handler["name"]
    if answer["confirmed"]:
        said = signed_off(context, claim)
        note = f"[{name} pressed Sign off and pay. {said}.]"
    else:
        note = (
            f"[{name} pressed Cancel. Nothing was signed off and {claim['claim_id']} "
            "is still waiting. Say so, and ask what they'd like instead.]"
        )
    return {"messages": [HumanMessage(note)], "confirmation": None}


def remember(state: CopilotState, runtime: Runtime[CopilotContext]) -> dict[str, Any]:
    """Save the handler's message and the answer to their memory, and nothing else."""
    context = runtime.context
    if context.memory is not None:
        memory.save_turn(
            context.memory,
            context.handler["handler_id"],
            context.conversation_id,
            state["asked"],
            state["messages"][-1].text,
        )
    return {}


def build(
    make_llm: Callable[[], BaseChatModel],
    tools: list[BaseTool],
    saver: BaseCheckpointSaver[Any],
) -> Any:
    """Build the Copilot's graph on this model, these tools and checkpointer."""
    builder = StateGraph(CopilotState, context_schema=CopilotContext)
    builder.add_node("start", start)
    builder.add_node("recall", recall)
    builder.add_node("model", model_node(make_llm, tools))
    builder.add_node("tools", ToolNode(tools, wrap_tool_call=record_tool_call))
    builder.add_node("confirm", confirm)
    builder.add_node("remember", remember)
    builder.add_edge(START, "start")
    builder.add_edge("start", "recall")
    builder.add_edge("recall", "model")
    builder.add_conditional_edges("model", after_model, ["tools", "remember"])
    builder.add_conditional_edges("tools", after_tools, ["confirm", "model"])
    builder.add_edge("confirm", "model")
    builder.add_edge("remember", END)
    return builder.compile(checkpointer=saver)


def tools_for_turn() -> list[BaseTool]:
    """The Copilot's tools, with the context layer on the route the settings give."""
    found = context_tools(
        os.getenv("UNDERCOVER_GATEWAY_URL"), os.getenv("UNDERCOVER_CONTEXT")
    )
    return [
        *RECORDS,
        what_needs_me,
        *found,
        *ACTIONS,
        wait_for_work,
        check_success_criteria,
    ]


def config_for(context: CopilotContext) -> RunnableConfig:
    """The conversation's thread, and nothing else: the config is saved."""
    return {
        "configurable": {"thread_id": context.conversation_id},
        "recursion_limit": RECURSION_LIMIT,
    }


def run(
    context: CopilotContext,
    given: dict[str, Any] | Command[Any],
    llm: BaseChatModel | None = None,
) -> None:
    """Run the graph to its end or its pause, then tell the app which: the answer
    with the turn's model calls and cost, or the card the turn waits on."""
    graph = build(
        (lambda: llm) if llm is not None else model.copilot_model,
        tools_for_turn(),
        checkpoints.saver(),
    )
    config = config_for(context)
    graph.invoke(given, config, context=context, durability="sync")
    saved = graph.get_state(config)
    path = turn_path(context)
    if saved.interrupts:
        card_waiting = saved.interrupts[0].value
        copilot_client.call(
            context.token, "POST", f"{path}/pause", {"confirmation": card_waiting}
        )
        return
    values = saved.values
    finished = {
        "answer": values["messages"][-1].text,
        "model_calls": values["model_calls"],
        "cost": values["cost"],
    }
    copilot_client.call(context.token, "POST", f"{path}/finish", finished)


def turn(
    context: CopilotContext, message: str, llm: BaseChatModel | None = None
) -> None:
    """Work one turn of a conversation: the handler's message, to its answer or
    its pause."""
    run(context, {"asked": message}, llm)


def answer(
    context: CopilotContext, confirmed: bool, llm: BaseChatModel | None = None
) -> None:
    """Carry a paused turn on with the handler's answer to its confirmation."""
    run(context, Command(resume={"confirmed": confirmed}), llm)
