"""The rules for a run, a dispatch or an evaluation: its claims, cost and time."""

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, func, select
from sqlalchemy.exc import IntegrityError

from backend import db, evaluations, versions
from backend.db import claims, run_claims, runs, steps, usage, work_sessions
from backend.rules import standing_of, standing_query
from backend.schemas import RunRecord

ALREADY_RUNNING = "A dispatch or evaluation is already running"


def dispatch_claims(conn: Connection) -> list[str]:
    """The claims a dispatch works: in progress first, then waiting, oldest first.

    An evaluation's copies are never among them.
    """
    query = select(claims.c.claim_id, claims.c.status, claims.c.body).where(
        claims.c.evaluation_id.is_(None),
        claims.c.status.in_(("in_progress", "waiting")),
    )
    found = sorted(
        (
            row["status"] != "in_progress",
            json.loads(row["body"])["submitted_on"],
            row["claim_id"],
        )
        for row in conn.execute(query).mappings()
    )
    return [claim_id for *_, claim_id in found]


def start(conn: Connection, record: RunRecord) -> int:
    """Create a run on a version and fix its claims; refuse it while another runs."""
    version = (
        versions.current(conn)
        if record.version is None
        else versions.find(conn, record.version)
    )
    try:
        result = conn.execute(
            runs.insert().values(
                **record.model_dump(exclude={"version"}),
                version=version["version"],
                model=version["model"],
                reasoning=version["reasoning"],
                total=0,
                status="running",
                started_at=db.now(),
            )
        )
    except IntegrityError:
        raise HTTPException(409, ALREADY_RUNNING) from None
    run_id = int(result.inserted_primary_key[0])  # type: ignore[index]
    if record.set_name is None:
        claim_ids = dispatch_claims(conn)
    else:
        claim_ids = evaluations.copy(conn, run_id, record.set_name, record.tiny)
    if claim_ids:
        conn.execute(
            run_claims.insert(),
            [
                {"run_id": run_id, "claim_id": claim_id, "position": position}
                for position, claim_id in enumerate(claim_ids, 1)
            ],
        )
    conn.execute(
        runs.update().where(runs.c.run_id == run_id).values(total=len(claim_ids))
    )
    return run_id


def find_run(conn: Connection, run_id: int) -> RowMapping:
    """Return a run, or raise 404."""
    row = conn.execute(select(runs).where(runs.c.run_id == run_id)).mappings().first()
    if row is None:
        raise HTTPException(404, f"No run {run_id}")
    return row


def end(conn: Connection, run_id: int, status: str) -> None:
    """End a running run as finished or stopped; its claims carry on next time."""
    update = (
        runs.update()
        .where(runs.c.run_id == run_id, runs.c.status == "running")
        .values(status=status, finished_at=db.now())
    )
    if conn.execute(update).rowcount == 0:
        raise HTTPException(409, f"Run {run_id} is {find_run(conn, run_id)['status']}")


def claim_entries(conn: Connection, run_id: int) -> list[dict[str, Any]]:
    """Each of the run's claims, in order: where it stands, its cost and its time."""
    in_run = select(run_claims.c.claim_id).where(run_claims.c.run_id == run_id)
    positions = dict(
        conn.execute(
            select(run_claims.c.claim_id, run_claims.c.position).where(
                run_claims.c.run_id == run_id
            )
        ).all()
    )
    costs = dict(
        conn.execute(
            select(usage.c.claim_id, func.sum(usage.c.cost))
            .where(usage.c.run_id == run_id)
            .group_by(usage.c.claim_id)
        ).all()
    )
    times = {
        row["claim_id"]: row
        for row in conn.execute(
            select(
                work_sessions.c.claim_id,
                func.sum(work_sessions.c.seconds).label("seconds"),
                func.min(work_sessions.c.started).label("started"),
            )
            .where(work_sessions.c.run_id == run_id)
            .group_by(work_sessions.c.claim_id)
        ).mappings()
    }
    latest = (
        select(steps.c.text)
        .where(steps.c.claim_id == claims.c.claim_id)
        .order_by(steps.c.step_id.desc())
        .limit(1)
        .scalar_subquery()
        .label("latest_step")
    )
    query = standing_query().add_columns(latest).where(claims.c.claim_id.in_(in_run))
    entries = []
    for row in conn.execute(query).mappings():
        found = standing_of(row)
        decision = found["decision"] or {}
        time = times.get(row["claim_id"], {})
        entries.append(
            {
                "claim_id": row["claim_id"],
                "source_id": row["source_id"],
                "status": found["status"],
                "attempts": found["attempts"],
                "agent_working": found["agent_working"],
                "latest_step": row["latest_step"],
                "decision": decision.get("decision"),
                "payout": decision.get("payout"),
                "reasons": decision.get("reasons"),
                "policy_section": decision.get("policy_section"),
                "paid": found["payment"] is not None,
                "cost": costs.get(row["claim_id"], 0.0),
                "seconds": time.get("seconds", 0.0),
                "started": time.get("started"),
            }
        )
    return sorted(entries, key=lambda entry: positions[entry["claim_id"]])


def summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The summary of an ended run, built from the records with no model."""
    decisions = [entry["decision"] for entry in entries]
    return {
        "approved": decisions.count("approve"),
        "declined": decisions.count("decline"),
        "referred": decisions.count("refer"),
        "awaiting_sign_off": [
            {"claim_id": entry["claim_id"], "payout": entry["payout"]}
            for entry in entries
            if entry["status"] == "awaiting_sign_off"
        ],
        "left_for_handler": [
            entry["claim_id"] for entry in entries if entry["status"] == "needs_handler"
        ],
        "in_progress": [
            entry["claim_id"] for entry in entries if entry["status"] == "in_progress"
        ],
    }


def elapsed(row: RowMapping) -> float:
    """The run's time from its start to its end, or to now while it's running."""
    ended = datetime.fromisoformat(row["finished_at"] or db.now())
    return (ended - datetime.fromisoformat(row["started_at"])).total_seconds()


def describe(conn: Connection, row: RowMapping) -> dict[str, Any]:
    """Return a run with its claims, its cost and time, and its summary once ended."""
    entries = claim_entries(conn, row["run_id"])
    return {
        **row,
        "tiny": bool(row["tiny"]),
        "claims": entries,
        "cost": sum(entry["cost"] for entry in entries),
        "seconds": sum(entry["seconds"] for entry in entries),
        "elapsed": elapsed(row),
        "summary": None if row["status"] == "running" else summarise(entries),
    }
