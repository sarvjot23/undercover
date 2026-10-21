"""The UnderCover Agent."""

import json
import os
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

load_dotenv(override=True)

BACKEND_URL = "http://localhost:8000"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-luna"
STEP_LENGTH = 600


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


def reply(response: httpx.Response) -> str:
    """Return the backend's response as text for the model, refusals included."""
    if response.is_success:
        return response.text
    return f"Refused ({response.status_code}): {response.json()['detail']}"


@tool
def get_claim(claim_id: str) -> str:
    """Get a claim with its policy, plan limits and the customer's claim history."""
    with backend() as client:
        response = client.get(f"/api/claims/{claim_id}")
    response.raise_for_status()
    return response.text


@tool
def get_policy_wording() -> str:
    """Get the policy wording that decisions follow."""
    with backend() as client:
        response = client.get("/api/policy-wording")
    response.raise_for_status()
    return response.json()["text"]


@tool
def record_decision(
    claim_id: str,
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    reasons: str,
    policy_section: str,
) -> str:
    """Record a decision with its payout, reasons and policy section."""
    with backend() as client:
        response = client.post(
            f"/api/claims/{claim_id}/decision",
            json={
                "decision": decision,
                "payout": payout,
                "reasons": reasons,
                "policy_section": policy_section,
            },
        )
    return reply(response)


@tool
def pay_claim(claim_id: str, amount: float) -> str:
    """Pay an approved claim's payout."""
    with backend() as client:
        response = client.post(
            f"/api/claims/{claim_id}/payment", json={"amount": amount}
        )
    return reply(response)


TOOLS = [get_claim, get_policy_wording, record_decision, pay_claim]


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or GPT-6 Luna by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
    )


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


def work(agent: Any, client: httpx.Client, claim_id: str, thread_id: str) -> str:
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
                    client.post(
                        f"/api/claims/{claim_id}/steps",
                        json={"kind": kind, "text": text},
                    )
                    if kind == "answer":
                        answer = text
    return answer


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the agent on one claim and return its final reply."""
    with backend() as client:
        client.post(f"/api/claims/{claim_id}/start").raise_for_status()
        instructions = client.get("/api/instructions").json()["text"]
        agent = create_agent(llm or model(), tools=TOOLS, system_prompt=instructions)
        try:
            answer = work(agent, client, claim_id, thread_id)
        except Exception as error:
            client.post(
                f"/api/claims/{claim_id}/fail",
                json={"reason": f"The agent's run failed: {error}"},
            )
            raise
        if client.get(f"/api/claims/{claim_id}").json()["status"] == "in_progress":
            client.post(
                f"/api/claims/{claim_id}/fail",
                json={"reason": "The agent finished without recording a decision"},
            )
    return answer
