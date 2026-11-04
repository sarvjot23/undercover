"""The model behind the UnderCover Agent."""

import os

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-luna"
TIMEOUT = 120


def describe() -> dict[str, str]:
    """Say which model the agent uses and its reasoning effort, as a run records it."""
    name = os.getenv("MODEL_NAME")
    return {"model": name or DEFAULT_MODEL, "reasoning": "none" if name else "low"}


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME with no effort set, or the default."""
    chosen = describe()
    return ChatOpenAI(
        model=chosen["model"],
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if chosen["reasoning"] == "none" else chosen["reasoning"],
        timeout=TIMEOUT,
        max_retries=0,
    )
