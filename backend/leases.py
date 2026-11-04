"""Leases: only one worker on a claim, and a killed worker's lease expires."""

from typing import Any

from sqlalchemy import Connection, Table, or_

from backend import db

LEASE_SECONDS = 20


def expiry() -> str:
    """Return when a lease taken now runs out."""
    return db.later(LEASE_SECONDS)


def take(conn: Connection, table: Table, key: Any, worker: str) -> bool:
    """Take or renew a lease in one update, so two workers can't both win."""
    update = (
        table.update()
        .where(
            table.primary_key.columns.values()[0] == key,
            or_(
                table.c.lease_owner.is_(None),
                table.c.lease_owner == worker,
                table.c.lease_until < db.now(),
            ),
        )
        .values(lease_owner=worker, lease_until=expiry())
    )
    return conn.execute(update).rowcount > 0


def release(conn: Connection, table: Table, key: Any, worker: str) -> None:
    """Give up a lease this worker holds."""
    conn.execute(
        table.update()
        .where(
            table.primary_key.columns.values()[0] == key,
            table.c.lease_owner == worker,
        )
        .values(lease_owner=None, lease_until=None)
    )
