"""A round's stretch of work in the agent's service: its evaluations, through the
dispatcher in this process, and the improver until it pauses or finishes."""

import json
from contextvars import Context
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent import dispatcher, improver, improver_client, tracing
from agent.tracing import Run

NO_VERSION = "There's no new version to evaluate. Propose a change first."
START = "Please carry out one round of your recipe."


def evaluate(round_id: int, version: int, sets: list[str], stage: str) -> bool:
    """Run a version's whole-set evaluations for a round, one after another, and
    say whether they all finished.

    Each runs through the dispatcher in a fresh context, as the harness runs each
    claim graph, so nothing is saved into the improver's thread.
    """
    found = improver_client.find(round_id)
    n = found["settings"]["agents_at_once"]
    for number, set_name in enumerate(sets, 1):
        improver_client.progress(round_id, stage, f"{number} of {len(sets)}")
        created = improver_client.create_evaluation(round_id, version, set_name, n)
        run: Run = {
            "run_id": created["run_id"],
            "kind": "evaluation",
            "version": version,
            "round_id": round_id,
        }
        Context().run(dispatcher.dispatch, run, n)
        if improver_client.run_status(created["run_id"]) != "finished":
            return False
    return True


def first_evaluations(round_id: int) -> bool:
    """Run the current version's missing whole-set evaluations, and say whether
    they all finished."""
    missing = improver_client.first_evaluations(round_id)
    if not missing["sets"]:
        return True
    return evaluate(round_id, missing["version"], missing["sets"], "first_evaluations")


def evaluate_version(round_id: int) -> str:
    """The run_evaluation tool: evaluate the version tried, then the verdict.

    An evaluation that might cost more than what's left of the limit is refused,
    and the version is rolled back.
    """
    found = improver_client.find(round_id)
    tried = found["version_tried"]
    if tried is None or found["verdict"] is not None:
        return NO_VERSION
    spending = improver_client.spending(round_id)
    if spending["estimate"] > spending["left"]:
        improver_client.judge(round_id, unaffordable=True)
        return (
            f"Refused: the evaluation could cost about ${spending['estimate']:.2f} "
            f"and ${spending['left']:.2f} of the spending limit is left. "
            f"Version {tried} is rolled back."
        )
    evaluate(round_id, tried, ["evaluation", "held_out", "held_out"], "evaluations")
    judged = improver_client.judge(round_id, unaffordable=False)
    kept = judged["verdict"] == "kept"
    current = tried if kept else found["version_before"]
    scores = {"held_out_before": judged["before"], "held_out_after": judged["after"]}
    return (
        f"{'Kept' if kept else 'Rolled back'} version {tried}: {judged['why']}. "
        f"Version {current} is now the current version.\n"
        f"{json.dumps(scores, indent=2)}"
    )


def improve(round_id: int, start: Any, llm: BaseChatModel | None = None) -> None:
    """Run the improver until it pauses for a handler or finishes the round."""
    found = improver_client.find(round_id)
    improver_client.progress(round_id, "improving", None)
    agent = improver.build(round_id, evaluate_version, llm)
    config = tracing.round_config(found["thread_id"], round_id)
    result = agent.invoke(start, config, durability="sync")
    tracing.flush()
    if improver_client.find(round_id)["status"] != "working":
        return
    waiting = result.get("__interrupt__")
    if not waiting:
        improver_client.finish(round_id)
        return
    request = waiting[0].value["action_requests"][0]
    args = request["args"]
    if request["name"] == "propose_change":
        improver_client.propose(
            round_id,
            "change",
            {
                "instructions": args["instructions"],
                "model": args["model"],
                "reasoning": args["reasoning_effort"],
                "reason": args["reason"],
            },
        )
    else:
        improver_client.propose(
            round_id, "recipe", {"recipe": args["recipe"], "reason": args["reason"]}
        )


def work(round_id: int, llm: BaseChatModel | None = None) -> None:
    """A round from its start: the first evaluations, then the improver."""
    if not first_evaluations(round_id):
        # Cut short by the spending limit, the round can't go on: it finishes with
        # no version tried. A round stopped by a handler is left as it is.
        if improver_client.find(round_id)["status"] == "working":
            improver_client.finish(round_id)
        return
    improve(round_id, {"messages": [HumanMessage(START)]}, llm)


def resume(
    round_id: int, decision: str, message: str, llm: BaseChatModel | None = None
) -> None:
    """Carry the improver on with a handler's decision, already recorded."""
    answer: dict[str, str] = {"type": decision}
    if decision == "reject":
        answer["message"] = message
    improve(round_id, Command(resume={"decisions": [answer]}), llm)
