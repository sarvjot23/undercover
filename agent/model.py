"""The models behind the UnderCover Agent: the claim agent's, built from a version
of its configuration, and the security check's, which no version changes."""

import os

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT = 120
# No reasoning effort set, which some models, Luna among them, call "none".
DEFAULT = "default"
CHECK_MODEL = "openai/gpt-6-luna"
CHECK_EFFORT = "none"


def platform_model() -> str | None:
    """The one model the platform runs on, if MODEL_NAME sets one."""
    return os.getenv("MODEL_NAME") or None


def chat(name: str, effort: str | None) -> ChatOpenAI:
    """A model on OpenRouter at this reasoning effort, or none set."""
    return ChatOpenAI(
        model=name,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=effort,
        timeout=TIMEOUT,
        max_retries=0,
    )


def model(name: str, reasoning: str) -> ChatOpenAI:
    """Return the model at this effort, or MODEL_NAME with no effort if it's set."""
    free = platform_model()
    return chat(free or name, None if free or reasoning == DEFAULT else reasoning)


def check_model() -> ChatOpenAI:
    """The security check's model: Luna at no reasoning, or MODEL_NAME with none."""
    free = platform_model()
    return chat(free or CHECK_MODEL, None if free else CHECK_EFFORT)
