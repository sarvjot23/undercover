"""Tracing in Langfuse: each claim's work is one session, named by its thread."""

import os
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langfuse import get_client
from langfuse.langchain import CallbackHandler


class Run(TypedDict):
    """The dispatch or evaluation a claim is worked in, on a version of the agent."""

    run_id: int
    kind: str
    version: int
    round_id: int | None


def enabled() -> bool:
    """Whether the Langfuse keys are in the environment."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY"))


def config(thread_id: str, recursion_limit: int, run: Run | None) -> RunnableConfig:
    """Return the config: its thread and run, and its Langfuse session and tags."""
    metadata: dict[str, Any] = {"langfuse_session_id": thread_id}
    if run:
        metadata["langfuse_tags"] = [f"{run['kind']}-{run['run_id']}"]
        if run["round_id"] is not None:
            metadata["langfuse_tags"].append(f"round-{run['round_id']}")
    return {
        "configurable": {
            "thread_id": thread_id,
            "run_id": run["run_id"] if run else None,
        },
        "callbacks": [CallbackHandler()] if enabled() else [],
        "metadata": metadata,
        "recursion_limit": recursion_limit,
    }


def flush() -> None:
    """Send what's been traced, so it isn't lost if the process stops."""
    if enabled():
        get_client().flush()


def round_config(thread_id: str, round_id: int) -> RunnableConfig:
    """The improver's config for a round: one Langfuse session, tagged with it."""
    return {
        "configurable": {"thread_id": thread_id},
        "callbacks": [CallbackHandler()] if enabled() else [],
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_tags": [f"round-{round_id}", "improver"],
        },
        "run_name": f"Improver round {round_id}",
    }
