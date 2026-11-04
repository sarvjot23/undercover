"""The improver, the agent's sixth part: it follows its recipe to improve the claim
agent, and pauses for a handler's approval of every proposal, as in the lab.

A LangChain agent on GPT-6 Luna at medium effort, one tool call a reply, with its
model calls capped for each round. Its tools are the lab's four and reach the
backend only through agent/improver_client.py. Each round works on a thread of
its own, saved in Postgres, so a round waiting for approval survives a restart.
"""

import json
from collections.abc import Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    hook_config,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool

from agent import checkpoints, improver_client
from agent.model import model

MODEL = "openai/gpt-6-luna"
EFFORT = "medium"
MODEL_CALLS = 20


def refusal(args: dict[str, Any]) -> str | None:
    """Why a proposed model and effort aren't allowed, or None if they are."""
    for allowed in improver_client.models_allowed():
        if allowed["model"] == args["model"]:
            if args["reasoning_effort"] in allowed["reasoning_efforts"]:
                return None
            efforts = ", ".join(allowed["reasoning_efforts"])
            return (
                f"{args['model']} at {args['reasoning_effort']} isn't allowed: its "
                f"efforts are {efforts}. Choose from the models allowed."
            )
    return f"{args['model']} isn't one of the models allowed. Choose from those."


class RoundGuard(AgentMiddleware):
    """Keeps the improver to its round: no model call once the round is stopped,
    one tool call a reply, and each reply's cost recorded with the round."""

    def __init__(self, round_id: int) -> None:
        super().__init__()
        self.round_id = round_id

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if improver_client.find(self.round_id)["status"] != "working":
            return {"jump_to": "end"}
        return None

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        settings = {**request.model_settings, "parallel_tool_calls": False}
        response = handler(request.override(model_settings=settings))
        for message in response.result:
            if isinstance(message, AIMessage):
                self.record(message)
        return response

    def record(self, reply: AIMessage) -> None:
        """Record a reply's tokens and cost, as OpenRouter reports them."""
        usage = reply.response_metadata.get("token_usage")
        if not usage:
            return
        improver_client.record_usage(
            self.round_id,
            {
                "model": reply.response_metadata.get("model_name", MODEL),
                "input_tokens": usage["prompt_tokens"],
                "output_tokens": usage["completion_tokens"],
                "cost": usage.get("cost", 0.0),
                "key": reply.id,
            },
        )


def make_tools(round_id: int, evaluate: Callable[[int], str]) -> list[BaseTool]:
    """The lab's four tools, for one round."""

    @tool
    def read_results() -> str:
        """Read the current version of the claim agent's configuration, its scores, its mistakes and weakest explanations on the evaluation set, the earlier rounds, the objectives, the noise and tolerance, our rule, what's left of the spending limit and the models allowed."""  # noqa: E501
        return json.dumps(improver_client.view(round_id), indent=2)

    @tool(parse_docstring=True)
    def propose_change(
        instructions: str, model: str, reasoning_effort: str, reason: str
    ) -> str:
        """Propose a new version of the claim agent's configuration. A handler reviews it before it's saved.

        Args:
            instructions: The claim agent's complete instructions
            model: One of the models allowed
            reasoning_effort: A reasoning effort allowed for that model
            reason: Why this change should improve the scores
        """  # noqa: E501
        refused = refusal({"model": model, "reasoning_effort": reasoning_effort})
        if refused:
            return refused
        version = improver_client.find(round_id)["version_tried"]
        return f"Saved as version {version}. Run the evaluation next."

    @tool
    def run_evaluation() -> str:
        """Run the new version once on the evaluation set and twice on the held-out set, then keep it or roll it back by our rule."""  # noqa: E501
        return evaluate(round_id)

    @tool(parse_docstring=True)
    def propose_recipe(recipe: str, reason: str) -> str:
        """Propose a new version of your recipe for improving the claim agent. A handler reviews it before it's saved.

        Args:
            recipe: The complete new recipe
            reason: What this round showed, and why the new recipe should lead to better changes
        """  # noqa: E501
        return "Saved as the new recipe. The next round follows it."

    return [read_results, propose_change, run_evaluation, propose_recipe]


def approval() -> HumanInTheLoopMiddleware:
    """Pause for a handler on each proposal; one outside the models allowed goes
    straight back to the improver."""
    change: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "when": lambda request: refusal(request.tool_call["args"]) is None,
    }
    recipe: InterruptOnConfig = {"allowed_decisions": ["approve", "reject"]}
    return HumanInTheLoopMiddleware(
        interrupt_on={"propose_change": change, "propose_recipe": recipe}
    )


def build(
    round_id: int,
    evaluate: Callable[[int], str],
    llm: BaseChatModel | None = None,
) -> Any:
    """Build the improver for a round, with the round's recipe in its instructions."""
    middleware: list[Any] = [
        RoundGuard(round_id),
        ModelCallLimitMiddleware(thread_limit=MODEL_CALLS, exit_behavior="end"),
        approval(),
    ]
    return create_agent(
        model=llm or model(MODEL, EFFORT),
        tools=make_tools(round_id, evaluate),
        system_prompt=improver_client.instructions(round_id),
        middleware=middleware,
        checkpointer=checkpoints.saver(),
        name="improver",
    )
