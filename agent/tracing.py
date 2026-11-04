"""Tracing in Langfuse: each claim's work is one session, named by its thread."""

import os
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langfuse import get_client
from langfuse.langchain import CallbackHandler


class Run(TypedDict):
    """The dispatch or evaluation a claim is worked in."""

    run_id: int
    kind: str


def enabled() -> bool:
    """Whether the Langfuse keys are in the environment."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY"))


def config(thread_id: str, recursion_limit: int, run: Run | None) -> RunnableConfig:
    """Return the config: its thread and run, and its Langfuse session and tag."""
    metadata: dict[str, Any] = {"langfuse_session_id": thread_id}
    if run:
        metadata["langfuse_tags"] = [f"{run['kind']}-{run['run_id']}"]
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
