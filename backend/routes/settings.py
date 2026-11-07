"""The platform's settings: every handler sees them, an approver changes them."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from backend import allowed, keys, settings
from backend.auth import over_the_limit
from backend.db import Db, SingleStatementDb
from backend.settings import Settings

router = APIRouter(prefix="/api/settings")

SettingsChanger = Annotated[
    dict[str, Any], Depends(over_the_limit("change the settings"))
]


def describe(conn: Any) -> dict[str, Any]:
    """The settings, who changed what, and the models allowed."""
    return {
        "settings": settings.current(conn).model_dump(),
        "changes": settings.changes(conn),
        "models": allowed.models(),
    }


@router.get("", operation_id="get_settings", dependencies=keys.READ)
def get_settings(conn: SingleStatementDb) -> dict[str, Any]:
    """Get the settings, their changes and the models the claim agent may use."""
    return describe(conn)


@router.put("", operation_id="change_settings")
def change_settings(
    new: Settings, handler: SettingsChanger, conn: Db
) -> dict[str, Any]:
    """Change the settings as the handler signed in, recording each change."""
    settings.change(conn, new, handler["handler_id"])
    conn.commit()
    return describe(conn)
