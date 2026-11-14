"""The claim agent's memory of each customer, and the Copilot's of each handler, in
AgentCore Memory.

On when UNDERCOVER_MEMORY_ID is set, in the AWS CLI's region, outside evaluations.
Each customer's memories are used only for that customer's claims (claims manual
section 11): events are saved with the customer as the actor and the claim as the
session, and a search stays under /customers/<that customer>.
"""

import logging
import os
import uuid
from typing import Any

import boto3
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.base import BaseStore
from langgraph_checkpoint_aws import AgentCoreMemoryStore

log = logging.getLogger(__name__)
SEARCH_LIMIT = 5


def for_run(kind: str | None) -> BaseStore | None:
    """The memory, read from the settings now; none in an evaluation, so its scores
    never depend on what was remembered."""
    memory_id = os.getenv("UNDERCOVER_MEMORY_ID")
    if not memory_id or kind == "evaluation":
        return None
    return AgentCoreMemoryStore(
        memory_id=memory_id, region_name=boto3.Session().region_name
    )


def claim_text(claim: dict[str, Any]) -> str:
    """The claim as the customer's message: never the story or the documents."""
    items = "; ".join(
        f"{item['description']} ${item['amount']:,.2f}" for item in claim["items"]
    )
    return (
        f"Claim {claim['claim_id']}: {claim['summary']}. "
        f"Benefit claimed: {claim['claim_type']}. "
        f"On {claim['incident_date']} in {claim['incident_location']}. "
        f"Items: {items}."
    )


def decision_text(claim: dict[str, Any]) -> str:
    """The decision as the agent's message."""
    decision = claim["decision"]
    return (
        f"Decision on {claim['claim_id']}: {decision['decision']}, "
        f"payout ${decision['payout']:,.2f}, section {decision['policy_section']}. "
        f"{decision['reasons']}"
    )


def save(memory: BaseStore, claim: dict[str, Any]) -> str:
    """Save the claim and its decision as two events, and say what was saved."""
    namespace = (claim["customer_id"], claim["claim_id"])
    said, decided = claim_text(claim), decision_text(claim)
    memory.put(namespace, uuid.uuid4().hex, {"message": HumanMessage(said)})
    memory.put(namespace, uuid.uuid4().hex, {"message": AIMessage(decided)})
    return f"{said} {decided}"


def search(memory: BaseStore, customer_id: str, claim_id: str, query: str) -> str:
    """What we remember of this customer, leaving out this claim's own summary.

    An error reaches the model as a refusal.
    """
    try:
        found = memory.search(
            ("customers", customer_id), query=query, limit=SEARCH_LIMIT
        )
    except Exception as error:  # noqa: BLE001 - any failure is the model's refusal
        return f"Refused by AgentCore Memory: {error}"
    this_claim = f"/claims/{claim_id}/"
    texts = [
        item.value["content"]
        for item in found
        if not any(this_claim in path for path in item.value.get("namespaces", []))
    ]
    return "\n".join(texts) or "Nothing remembered about this customer yet."


# The Copilot's memory of each handler, in a Memory of its own: the handler is the
# actor, and the conversation the session. Notes land under /handlers/<handler>/.
RECALL_LIMIT = 5


def for_copilot() -> BaseStore | None:
    """The Copilot's memory, read from the settings now; none when it's off."""
    memory_id = os.getenv("UNDERCOVER_COPILOT_MEMORY_ID")
    if not memory_id:
        return None
    return AgentCoreMemoryStore(
        memory_id=memory_id, region_name=boto3.Session().region_name
    )


def recall(memory: BaseStore, handler_id: str, query: str) -> list[str]:
    """What the Copilot remembers about this handler that bears on the message,
    and nothing about anyone else. A store that can't be reached finds nothing."""
    try:
        found = memory.search(("handlers", handler_id), query=query, limit=RECALL_LIMIT)
    except Exception:  # noqa: BLE001 - the turn goes on without its memory
        log.warning("The Copilot's memory couldn't be searched", exc_info=True)
        return []
    return [item.value["content"] for item in found]


def save_turn(
    memory: BaseStore, handler_id: str, conversation_id: str, message: str, answer: str
) -> None:
    """Save the handler's message and the Copilot's answer, and nothing else."""
    namespace = (handler_id, conversation_id)
    try:
        memory.put(namespace, uuid.uuid4().hex, {"message": HumanMessage(message)})
        memory.put(namespace, uuid.uuid4().hex, {"message": AIMessage(answer)})
    except Exception:  # noqa: BLE001 - the answer stands without its memory
        log.warning("The Copilot's memory couldn't be saved", exc_info=True)
