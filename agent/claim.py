"""The claim agent: decides one claim, recording each step on it."""

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from agent import client
from agent.middleware import StepRecorder
from agent.model import model
from agent.tools import TOOLS


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the agent on one claim and return its final reply."""
    with client.backend() as backend:
        backend.post(f"/api/claims/{claim_id}/start").raise_for_status()
        instructions = backend.get("/api/instructions").json()["text"]
        agent = create_agent(
            llm or model(),
            tools=TOOLS,
            system_prompt=instructions,
            middleware=[StepRecorder(backend, claim_id)],
        )
        try:
            result = agent.invoke(
                {
                    "messages": [
                        {"role": "user", "content": f"Decide claim {claim_id}."}
                    ]
                },
                config={"configurable": {"thread_id": thread_id}},
            )
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
    return result["messages"][-1].text
