"""Tracing in Langfuse: each claim's work is one session, named by its thread."""

import os

from langchain_core.runnables import RunnableConfig
from langfuse import get_client
from langfuse.langchain import CallbackHandler


def enabled() -> bool:
    """Whether the Langfuse keys are in the environment."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY"))


def config(thread_id: str, recursion_limit: int) -> RunnableConfig:
    """Return the run's config: its thread, and its Langfuse session if traced."""
    return {
        "configurable": {"thread_id": thread_id},
        "callbacks": [CallbackHandler()] if enabled() else [],
        "metadata": {"langfuse_session_id": thread_id},
        "recursion_limit": recursion_limit,
    }


def flush() -> None:
    """Send what's been traced, so it isn't lost if the process stops."""
    if enabled():
        get_client().flush()
