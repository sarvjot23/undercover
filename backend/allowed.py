"""The models the claim agent may use, set in data/models.json, never on a page.

With MODEL_NAME set, as on the free route, that model is the only one allowed, at
reasoning effort default and a price of 0.
"""

import os
from typing import Any

from backend import db


def models() -> list[dict[str, Any]]:
    """Each model allowed, with its reasoning efforts and prices per million tokens."""
    free = os.getenv("MODEL_NAME")
    if free:
        return [
            {
                "model": free,
                "reasoning_efforts": ["default"],
                "input_price": 0.0,
                "output_price": 0.0,
            }
        ]
    return db.load("models.json")


def find(model: str) -> dict[str, Any] | None:
    """A model allowed, or None."""
    return next((found for found in models() if found["model"] == model), None)


def refusal(model: str, reasoning: str) -> str | None:
    """Why a model and effort aren't allowed, or None if they are."""
    found = find(model)
    if found is None:
        names = ", ".join(entry["model"] for entry in models())
        return f"{model} isn't one of the models allowed: {names}"
    if reasoning not in found["reasoning_efforts"]:
        efforts = ", ".join(found["reasoning_efforts"])
        return f"{model} allows the reasoning efforts {efforts}, not {reasoning}"
    return None
