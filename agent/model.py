"""The model behind the UnderCover Agent, built from a version of its configuration."""

import os

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT = 120
# No reasoning effort set, which some models, Luna among them, call "none".
DEFAULT = "default"


def model(name: str, reasoning: str) -> ChatOpenAI:
    """Return the model at this effort, or MODEL_NAME with no effort if it's set."""
    free = os.getenv("MODEL_NAME")
    effort = None if free or reasoning == DEFAULT else reasoning
    return ChatOpenAI(
        model=free or name,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=effort,
        timeout=TIMEOUT,
        max_retries=0,
    )
