"""The platform's settings, kept in the database: every part reads them from here."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Connection, select

from backend import db
from backend.db import setting_changes, settings

MAX_AGENTS = 25


class Measures(BaseModel):
    """A margin for each measure: accuracy and the grade as differences, cost and time
    as fractions of the old value."""

    accuracy: float = Field(ge=0, le=1)
    grade: float = Field(ge=0, le=3)
    cost_per_claim: float = Field(ge=0)
    seconds_per_claim: float = Field(ge=0)


class Objectives(BaseModel):
    """The floors on held-out accuracy and on the judge's grade."""

    accuracy: float = Field(ge=0, le=1)
    grade: float = Field(ge=0, le=3)


class Settings(BaseModel):
    """The settings a handler who can sign off over the limit may change."""

    approval_limit: float = Field(gt=0)
    objectives: Objectives
    noise: Measures
    tolerance: Measures
    round_spending_limit: float = Field(gt=0)
    agents_at_once: int = Field(ge=1, le=MAX_AGENTS)


def unflatten(flat: dict[str, float]) -> dict[str, Any]:
    """Names such as noise.accuracy back into nested settings."""
    nested: dict[str, Any] = {}
    for name, value in flat.items():
        *groups, last = name.split(".")
        place = nested
        for group in groups:
            place = place.setdefault(group, {})
        place[last] = value
    return nested


def current(conn: Connection) -> Settings:
    """The settings as they stand."""
    rows = conn.execute(select(settings.c.name, settings.c.value)).all()
    return Settings.model_validate(unflatten(dict(rows)))  # type: ignore[arg-type]


def change(conn: Connection, new: Settings, handler_id: str) -> list[str]:
    """Save the settings that differ, each change with who made it and when."""
    before = db.flatten(current(conn).model_dump())
    changed = []
    for name, value in db.flatten(new.model_dump()).items():
        if value == before[name]:
            continue
        conn.execute(
            settings.update().where(settings.c.name == name).values(value=value)
        )
        conn.execute(
            setting_changes.insert().values(
                name=name,
                before=before[name],
                after=value,
                handler_id=handler_id,
                changed_at=db.now(),
            )
        )
        changed.append(name)
    return changed


def changes(conn: Connection) -> list[dict[str, Any]]:
    """Every change to the settings, newest first."""
    query = select(setting_changes).order_by(setting_changes.c.change_id.desc())
    return [dict(row) for row in conn.execute(query).mappings()]
