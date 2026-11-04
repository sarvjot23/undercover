"""Where the claim graph saves its progress: Supabase, beside our other tables."""

import atexit
import os
from functools import lru_cache
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = "undercover"
MAX_CONNECTIONS = 4
# A claim agent waits this long for one of the 4 connections rather than failing.
POOL_TIMEOUT = 120


@lru_cache
def pool(url: str) -> ConnectionPool[Any]:
    """Open this process's pool of at most 4 connections, in our own schema."""
    settings: dict[str, Any] = {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
        "options": f"-c search_path={SCHEMA}",
    }
    opened: ConnectionPool[Any] = ConnectionPool(
        url,
        min_size=2,
        max_size=MAX_CONNECTIONS,
        timeout=POOL_TIMEOUT,
        kwargs=settings,
        open=True,
    )
    atexit.register(opened.close)
    with opened.connection() as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    PostgresSaver(opened).setup()  # type: ignore[arg-type]
    return opened


@lru_cache
def memory() -> InMemorySaver:
    """The checkpointer in memory, shared by the process; only the tests use it."""
    return InMemorySaver()


def saver() -> BaseCheckpointSaver[Any]:
    """Return a checkpointer for one run of the graph, on the process's shared pool.

    A PostgresSaver holds a lock around every read and write, so claim agents that
    shared one would take turns.
    """
    url = os.getenv("DATABASE_URL")
    return PostgresSaver(pool(url)) if url else memory()  # type: ignore[arg-type]
