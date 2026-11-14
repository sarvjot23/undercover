"""The Copilot's tools: our records, the context layer and the agent's work, each
called through the app as the handler who asked.

The handler's sign-in reaches each tool in the graph's context, read through
ToolRuntime, and never in its state or config, which LangGraph saves.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

import boto3
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool, tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.store.base import BaseStore
from langgraph.types import Command

from agent import copilot_client, mcp_bridge
from agent.copilot_client import Refused
from agent.direct import CONTEXT, DEFAULT_CONTEXT
from agent.gateway import SigV4Auth

STEPS_SHOWN = 40
# Each tool's kind, which gives its card an icon; any action stands out.
KINDS = {
    "list_claims": "claims",
    "what_needs_me": "claims",
    "get_claim": "claims",
    "get_claim_steps": "claims",
    "get_policy": "customers",
    "get_customer": "customers",
    "find_customers": "customers",
    "get_latest_dispatch": "work",
    "list_evaluations": "work",
    "get_evaluation": "work",
    "get_settings": "work",
    "wait_for_work": "work",
    "start_dispatch": "action",
    "start_evaluation": "action",
    "send_back": "action",
    "sign_off_claim": "action",
    "check_success_criteria": "action",
}
CANT_ACT = (
    "{name} can't sign off payouts over the limit, so the Copilot can't {action} "
    "for them. A handler who can sign off over the limit can."
)


@dataclass(frozen=True)
class CopilotContext:
    """Who the Copilot works for on this turn, given with each run of its graph and
    never saved: the sign-in, the handler the app says it is, the conversation,
    the turn and the handler's memory."""

    token: str
    handler: dict[str, Any]
    conversation_id: str
    turn_id: int
    memory: BaseStore | None


Runtime = ToolRuntime[CopilotContext, Any]


def as_text(found: Any) -> str:
    """An answer for the model, as JSON."""
    return json.dumps(found, ensure_ascii=False)


def ask(context: CopilotContext, method: str, path: str, body: Any = None) -> Any:
    """Call the app as the handler; raise Refused with the app's reason."""
    return copilot_client.call(context.token, method, path, body)


def read(context: CopilotContext, path: str) -> str:
    """Read from the app as the handler; a refusal is the model's answer."""
    try:
        return as_text(ask(context, "GET", path))
    except Refused as refused:
        return str(refused)


def may_act(context: CopilotContext, action: str) -> str | None:
    """Why this handler can't sign off or send back, checked before any call."""
    handler = context.handler
    if handler["can_approve_over_limit"]:
        return None
    return "Refused: " + CANT_ACT.format(name=handler["name"], action=action)


def agents_at_once(context: CopilotContext, agents: int | None) -> int:
    """The claim agents the handler asked for, or the number in our settings."""
    if agents is not None:
        return agents
    return int(ask(context, "GET", "/api/settings")["settings"]["agents_at_once"])


def started(context: CopilotContext, path: str, body: dict[str, Any]) -> str:
    """Start a dispatch or an evaluation; say which run it is, or why not."""
    try:
        run = ask(context, "POST", path, body)
    except Refused as refused:
        return str(refused)
    return as_text({"started": True, "run_id": run["run_id"]})


@tool
def list_claims(runtime: Runtime) -> str:
    """List the claims queue with where each claim stands and any decision."""
    try:
        found = ask(runtime.context, "GET", "/api/claims")
    except Refused as refused:
        return str(refused)
    fields = ("claim_id", "customer_name", "claim_type", "status", "decision")
    return as_text(
        [
            {**{k: claim[k] for k in fields}, "payout": claim["payout"]}
            for claim in found
        ]
    )


@tool
def get_claim(claim_id: str, runtime: Runtime) -> str:
    """Get a claim in full: its story, policy, customer, decision, payout and payment,
    and each decision sent back with its note."""
    try:
        claim = ask(runtime.context, "GET", f"/api/claims/{claim_id}")
        back = ask(runtime.context, "GET", f"/api/claims/{claim_id}/sent-back")
    except Refused as refused:
        return str(refused)
    return as_text({**claim, "sent_back": back})


@tool
def get_claim_steps(claim_id: str, runtime: Runtime) -> str:
    """Get the agent's latest steps on a claim: its tool calls, lookups and answer."""
    try:
        found = ask(runtime.context, "GET", f"/api/claims/{claim_id}/steps")
    except Refused as refused:
        return str(refused)
    return as_text(
        [{"kind": s["kind"], "text": s["text"]} for s in found[-STEPS_SHOWN:]]
    )


@tool
def get_policy(policy_id: str, runtime: Runtime) -> str:
    """Get a policy with its plan's limits."""
    return read(runtime.context, f"/api/policies/{policy_id}")


@tool
def get_customer(customer_id: str, runtime: Runtime) -> str:
    """Get a customer: who they are, their policies, their earlier claims and their
    claims in our queue."""
    return read(runtime.context, f"/api/customers/{customer_id}")


@tool
def find_customers(name: str, runtime: Runtime) -> str:
    """Find customers by name, or part of it, in any case."""
    return read(runtime.context, f"/api/customers/named/{name}")


@tool
def get_latest_dispatch(runtime: Runtime) -> str:
    """Get the latest dispatch: its status, cost, time and summary once it ends."""
    try:
        run = ask(runtime.context, "GET", "/api/runs/current")
    except Refused as refused:
        return str(refused)
    if run is None:
        return "No dispatch yet"
    return as_text({k: v for k, v in run.items() if k != "claims"})


@tool
def list_evaluations(runtime: Runtime) -> str:
    """List the evaluations, newest first, with their measures."""
    return read(runtime.context, "/api/evaluations")


@tool
def get_evaluation(run_id: int, runtime: Runtime) -> str:
    """Get one evaluation's status and measures."""
    return read(runtime.context, f"/api/evaluations/{run_id}/measures")


@tool
def get_settings(runtime: Runtime) -> str:
    """Get our settings: the approval limit, the objectives and the agents at once."""
    return read(runtime.context, "/api/settings")


@tool
def start_dispatch(runtime: Runtime, agents: int | None = None) -> str:
    """Start a dispatch of the queue with this many claim agents at once (1 to 25),
    or the number in our settings when the handler doesn't say."""
    context = runtime.context
    n = agents_at_once(context, agents)
    return started(context, "/api/dispatches", {"n": n})


@tool
def start_evaluation(
    labelled_set: Literal["evaluation", "held_out"],
    tiny: bool,
    runtime: Runtime,
    agents: int | None = None,
) -> str:
    """Start an evaluation of a labelled set, whole or only its five tiny claims,
    with this many claim agents at once, or the number in our settings."""
    context = runtime.context
    body = {
        "set_name": labelled_set,
        "tiny": tiny,
        "n": agents_at_once(context, agents),
    }
    return started(context, "/api/evaluations", body)


@tool
def send_back(claim_id: str, note: str, runtime: Runtime) -> str:
    """Send a decision held for sign-off back to the agent with a note saying what
    to look at again."""
    context = runtime.context
    refused = may_act(context, "send a decision back")
    if refused:
        return refused
    try:
        claim = ask(
            context, "POST", f"/api/claims/{claim_id}/send-back", {"note": note}
        )
    except Refused as refusal:
        return str(refusal)
    return as_text({"sent_back": True, "claim_id": claim_id, "status": claim["status"]})


def card_for(context: CopilotContext, claim_id: str) -> dict[str, Any] | str:
    """The confirmation card from our records, or why it can't be shown."""
    standing = ask(context, "GET", f"/api/claims/{claim_id}/standing")
    if standing["evaluation_id"] is not None:
        return f"Refused: {claim_id} is a copy for an evaluation"
    if standing["status"] != "awaiting_sign_off":
        return f"Refused: {claim_id} isn't waiting for a sign-off"
    claim = ask(context, "GET", f"/api/claims/{claim_id}")
    decision = standing["decision"]
    return {
        "claim_id": claim_id,
        "customer": claim["customer"]["name"],
        "amount": decision["payout"],
        "reason": decision["reasons"],
        "policy_section": decision["policy_section"],
    }


@tool
def sign_off_claim(claim_id: str, runtime: Runtime) -> Command[Any] | str:
    """Sign off a payout held for sign-off, which pays it. The handler confirms on
    a card first, and nothing is paid until they do."""
    context = runtime.context
    call_id = runtime.tool_call_id or ""
    refused = may_act(context, "sign off a payout")
    if refused:
        return refused
    try:
        card = card_for(context, claim_id)
    except Refused as refusal:
        return str(refusal)
    if isinstance(card, str):
        return card
    waiting = (
        f"Waiting for {context.handler['name']} to confirm the sign-off of "
        f"{claim_id}, paying ${card['amount']:,.2f}"
    )
    return Command(
        update={
            "confirmation": card,
            "messages": [ToolMessage(waiting, tool_call_id=call_id)],
        }
    )


RECORDS: list[BaseTool] = [
    list_claims,
    get_claim,
    get_claim_steps,
    get_policy,
    get_customer,
    find_customers,
    get_latest_dispatch,
    list_evaluations,
    get_evaluation,
    get_settings,
]
ACTIONS: list[BaseTool] = [start_dispatch, start_evaluation, send_back, sign_off_claim]


def own_name(name: str) -> str:
    """A tool's own name: the Gateway names each tool after its target."""
    return name.rsplit("___", 1)[-1]


def text_of(content: Any) -> str:
    """The text of an MCP tool's answer, which comes as text or as blocks."""
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content)


def synchronous(found: BaseTool) -> BaseTool:
    """An MCP tool the Copilot calls synchronously, on a loop of its own."""

    def call(**arguments: Any) -> str:
        try:
            return text_of(mcp_bridge.run(found.ainvoke(arguments)))
        except Exception as error:  # noqa: BLE001 - the model hears what went wrong
            return f"Refused by the context layer: {error}"

    return StructuredTool.from_function(
        func=call,
        name=own_name(found.name),
        description=found.description,
        args_schema=found.args_schema,
    )


def context_tools(gateway_url: str | None, context_url: str | None) -> list[BaseTool]:
    """The context layer's seven lookups over MCP, on the claim agent's route: through
    the Gateway, only the context layer's own tools, since the app's tools there act
    as the agent; otherwise straight to the context layer."""
    if gateway_url:
        connection: Any = {
            "transport": "streamable_http",
            "url": gateway_url,
            "auth": SigV4Auth(boto3.Session()),
        }
    else:
        connection = {
            "transport": "streamable_http",
            "url": context_url or DEFAULT_CONTEXT,
        }
    client = MultiServerMCPClient({"context": connection})
    found = mcp_bridge.run(client.get_tools())
    if gateway_url:
        found = [t for t in found if t.name.startswith(f"{CONTEXT}___")]
    return [synchronous(t) for t in found]
