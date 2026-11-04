"""The claim agent's configuration and the improver's recipe, in versions."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from backend import diffs, versions
from backend.db import SingleStatementDb, recipe_versions

router = APIRouter(prefix="/api")


@router.get("/configuration/current", operation_id="get_current_configuration")
def get_current_configuration(conn: SingleStatementDb) -> dict[str, Any]:
    """Get the current version: the claim agent's instructions, model and effort."""
    return versions.for_the_agent(versions.current(conn))


@router.get("/configuration/versions", operation_id="list_configuration_versions")
def list_configuration_versions(conn: SingleStatementDb) -> list[dict[str, Any]]:
    """List every version, newest first, with what it changed and its scores."""
    return versions.listing(conn)


@router.get(
    "/configuration/versions/{version}", operation_id="get_configuration_version"
)
def get_configuration_version(version: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get a version's instructions, model and effort, for the claim agent."""
    return versions.for_the_agent(versions.find(conn, version))


@router.get(
    "/configuration/versions/{version}/diff", operation_id="diff_configuration_version"
)
def diff_configuration_version(version: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get what a version changed from the one before it."""
    after = versions.find(conn, version)
    before = versions.find(conn, version - 1) if version > 1 else None
    return {
        "version": version,
        "before": before["version"] if before else None,
        "instructions": diffs.lines(
            before["instructions"] if before else "", after["instructions"]
        ),
        "model": [before["model"] if before else None, after["model"]],
        "reasoning": [before["reasoning"] if before else None, after["reasoning"]],
    }


@router.get("/recipes", operation_id="list_recipe_versions")
def list_recipe_versions(conn: SingleStatementDb) -> list[dict[str, Any]]:
    """List the improver's recipe in its versions, newest first."""
    query = select(recipe_versions).order_by(recipe_versions.c.version.desc())
    return [dict(row) for row in conn.execute(query).mappings()]


@router.get("/recipes/{version}/diff", operation_id="diff_recipe_version")
def diff_recipe_version(version: int, conn: SingleStatementDb) -> dict[str, Any]:
    """Get what a version of the recipe changed from the one before it."""
    after = versions.find_recipe(conn, version)
    before = versions.find_recipe(conn, version - 1) if version > 1 else None
    return {
        "version": version,
        "before": before["version"] if before else None,
        "recipe": diffs.lines(before["recipe"] if before else "", after["recipe"]),
    }
