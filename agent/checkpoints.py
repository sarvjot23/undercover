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


def postgres_saver(url: str) -> PostgresSaver:
    """Connect the checkpointer with at most 4 connections, in our own schema."""
    settings: dict[str, Any] = {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
        "options": f"-c search_path={SCHEMA}",
    }
    pool = ConnectionPool(
        url,
        min_size=2,
        max_size=MAX_CONNECTIONS,
        kwargs=settings,
        open=True,
    )
    atexit.register(pool.close)
    with pool.connection() as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    saver = PostgresSaver(pool)  # type: ignore[arg-type]
    saver.setup()
    return saver


@lru_cache
def saver() -> BaseCheckpointSaver[Any]:
    """Return this process's checkpointer; in memory only without DATABASE_URL."""
    url = os.getenv("DATABASE_URL")
    return postgres_saver(url) if url else InMemorySaver()
