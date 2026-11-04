"""A round of improvement, as the backend records it. The agent's service does the
work and records each step here; once a round is stopped, nothing more is recorded.

Stages: first_evaluations, improving, change_waiting, evaluations, verdict,
recipe_waiting, finished and stopped. A round is working while the service holds
it, waiting while a proposal waits for a handler, and then finished or stopped.
"""

import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, select
from sqlalchemy.dialects.postgresql import insert

from backend import allowed, db, diffs, settings, spending, versions
from backend.db import config_versions, recipe_versions, round_events, rounds
from backend.verdict import keep_or_roll_back

OPEN = ("working", "waiting")
NEEDED = ("evaluation", "held_out", "held_out")


def find(conn: Connection, round_id: int) -> RowMapping:
    """A round, or 404."""
    row = (
        conn.execute(select(rounds).where(rounds.c.round_id == round_id))
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, f"No round {round_id}")
    return row


def open_round(conn: Connection) -> RowMapping | None:
    """The round that is open, working or waiting for a handler, if there is one."""
    query = select(rounds).where(rounds.c.status.in_(OPEN))
    return conn.execute(query).mappings().first()


def writable(conn: Connection, round_id: int) -> RowMapping:
    """A round still open, or 409: a stopped round records nothing more."""
    row = find(conn, round_id)
    if row["status"] not in OPEN:
        raise HTTPException(409, f"Round {round_id} is {row['status']}")
    return row


def update(conn: Connection, round_id: int, **values: Any) -> None:
    """Change a round's record."""
    conn.execute(rounds.update().where(rounds.c.round_id == round_id).values(**values))


def create(conn: Connection, handler_id: str) -> RowMapping:
    """Open a round on its own copy of the settings and the latest recipe."""
    found = open_round(conn)
    if found:
        raise HTTPException(409, f"Round {found['round_id']} is open")
    result = conn.execute(
        rounds.insert().values(
            recipe_version=versions.latest_recipe(conn)["version"],
            settings=settings.current(conn).model_dump_json(),
            status="working",
            stage="improving",
            version_before=versions.current(conn)["version"],
            started_by=handler_id,
            started_at=db.now(),
        )
    )
    round_id = int(result.inserted_primary_key[0])  # type: ignore[index]
    # A new thread for every round, so a reseed never meets an old round's work.
    update(conn, round_id, thread_id=f"round-{round_id}-{uuid.uuid4().hex[:8]}")
    return find(conn, round_id)


def first_evaluations(conn: Connection) -> list[str]:
    """The whole-set evaluations the current version still needs: one on the
    evaluation set and two on the held-out set."""
    version = versions.current(conn)["version"]
    missing: list[str] = list(NEEDED)
    for set_name in versions.SETS:
        for _ in versions.round_evaluations(conn, version, set_name):
            if set_name in missing:
                missing.remove(set_name)
    return missing


def progress(conn: Connection, round_id: int, stage: str, step: str | None) -> None:
    """Record where a working round has got to, such as evaluations, 2 of 3."""
    writable(conn, round_id)
    update(conn, round_id, stage=stage, progress=step, status="working")


def propose(conn: Connection, round_id: int, proposal: dict[str, Any]) -> None:
    """Record a proposal waiting for a handler: a change or a recipe."""
    writable(conn, round_id)
    if proposal["kind"] == "change":
        refused = allowed.refusal(proposal["model"], proposal["reasoning"])
        if refused:
            raise HTTPException(422, refused)
    update(
        conn,
        round_id,
        proposal=json.dumps(proposal),
        stage=f"{proposal['kind']}_waiting",
        progress=None,
        status="waiting",
    )


def approve(
    conn: Connection, row: RowMapping, proposal: dict[str, Any], by: str
) -> None:
    """Save an approved proposal as a new version: a change isn't current yet."""
    if proposal["kind"] == "change":
        version = versions.next_number(conn, config_versions)
        conn.execute(
            config_versions.insert().values(
                version=version,
                instructions=proposal["instructions"],
                model=proposal["model"],
                reasoning=proposal["reasoning"],
                reason=proposal["reason"],
                proposed_by="improver",
                approved_by=by,
                approved_at=db.now(),
                current=False,
            )
        )
        update(conn, row["round_id"], version_tried=version, reason=proposal["reason"])
        return
    conn.execute(
        recipe_versions.insert().values(
            version=versions.next_number(conn, recipe_versions),
            recipe=proposal["recipe"],
            reason=proposal["reason"],
            proposed_by="improver",
            approved_by=by,
            approved_at=db.now(),
        )
    )


def decide(
    conn: Connection, round_id: int, decision: str, message: str, handler_id: str
) -> None:
    """Record a handler's approval or rejection of the proposal waiting."""
    row = writable(conn, round_id)
    if row["proposal"] is None:
        raise HTTPException(409, f"Round {round_id} has nothing waiting for approval")
    proposal = json.loads(row["proposal"])
    if decision == "approve":
        approve(conn, row, proposal, handler_id)
    conn.execute(
        round_events.insert().values(
            round_id=round_id,
            decision=decision,
            proposal=proposal["kind"],
            handler_id=handler_id,
            message=message,
            at=db.now(),
        )
    )
    update(
        conn,
        round_id,
        proposal=None,
        stage="improving",
        progress=None,
        status="working",
    )


def held_out(conn: Connection, version: int, round_id: int | None) -> Any:
    """A version's held-out average, counting a round's runs only if it finished
    all three."""
    runs = versions.round_evaluations(conn, version, "held_out")
    if round_id is not None:
        own = [run for run in runs if run["round_id"] == round_id]
        tried = versions.round_evaluations(conn, version, "evaluation")
        if len(own) < len(NEEDED) - 1 or not any(
            run["round_id"] == round_id for run in tried
        ):
            return None
    return versions.scores(conn, version)["held_out"]


def judge_version(conn: Connection, round_id: int, unaffordable: bool) -> None:
    """Keep the version tried or roll it back by our rule, with the round's settings.

    A version the round couldn't afford to evaluate, or whose evaluations were
    stopped, is rolled back. A kept version becomes the current version.
    """
    row = writable(conn, round_id)
    tried = row["version_tried"]
    if tried is None:
        raise HTTPException(409, f"Round {round_id} has no version to judge")
    before = held_out(conn, row["version_before"], None)
    after = None if unaffordable else held_out(conn, tried, round_id)
    if unaffordable:
        keep, why = False, "the round couldn't afford to evaluate it"
    elif before is None:
        keep, why = False, "the current version has no held-out scores to compare"
    else:
        keep, why = keep_or_roll_back(after, before, json.loads(row["settings"]))
    if keep:
        conn.execute(config_versions.update().values(current=False))
        conn.execute(
            config_versions.update()
            .where(config_versions.c.version == tried)
            .values(current=True)
        )
    update(
        conn,
        round_id,
        before=json.dumps(before),
        after=json.dumps(after),
        verdict="kept" if keep else "rolled_back",
        why=why,
        stage="verdict",
        progress=None,
    )


def end(conn: Connection, round_id: int, status: str) -> None:
    """Finish or stop an open round. A version tried with no verdict is rolled back,
    and never becomes the current version."""
    row = writable(conn, round_id)
    values: dict[str, Any] = {}
    if row["version_tried"] is not None and row["verdict"] is None:
        values = {"verdict": "rolled_back", "why": f"the round was {status}"}
    update(
        conn,
        round_id,
        status=status,
        stage=status,
        progress=None,
        proposal=None,
        finished_at=db.now(),
        **values,
    )


def round_spending(conn: Connection, row: RowMapping) -> dict[str, Any]:
    """A round's limit, what it has spent and what's left, and whether it's open."""
    limit = json.loads(row["settings"])["round_spending_limit"]
    used = spending.spent(conn, row["round_id"])
    estimate = None
    if row["version_tried"] is not None:
        model = versions.find(conn, row["version_tried"])["model"]
        current = versions.find(conn, row["version_before"])["model"]
        claims = spending.whole_set_claims(conn)
        estimate = claims * spending.per_claim(conn, model, current)
    return {
        "limit": limit,
        "spent": used,
        "left": max(0.0, limit - used),
        "open": row["status"] in OPEN,
        "estimate": estimate,
    }


def proposal_with_diff(conn: Connection, raw: str | None) -> dict[str, Any] | None:
    """The proposal waiting, with what it would change."""
    if raw is None:
        return None
    proposal = json.loads(raw)
    if proposal["kind"] == "recipe":
        latest = versions.latest_recipe(conn)
        return {**proposal, "diff": diffs.lines(latest["recipe"], proposal["recipe"])}
    current = versions.current(conn)
    return {
        **proposal,
        "diff": diffs.lines(current["instructions"], proposal["instructions"]),
        "model_before": current["model"],
        "reasoning_before": current["reasoning"],
    }


def describe(conn: Connection, row: RowMapping) -> dict[str, Any]:
    """A round as the Improvement page shows it."""
    events = select(round_events).where(round_events.c.round_id == row["round_id"])
    evaluations = select(
        db.runs.c.run_id,
        db.runs.c.set_name,
        db.runs.c.version,
        db.runs.c.status,
    ).where(db.runs.c.round_id == row["round_id"])
    tried = row["version_tried"]
    return {
        **row,
        "settings": json.loads(row["settings"]),
        "proposal": proposal_with_diff(conn, row["proposal"]),
        "before": json.loads(row["before"]) if row["before"] else None,
        "after": json.loads(row["after"]) if row["after"] else None,
        "tried": versions.for_the_agent(versions.find(conn, tried)) if tried else None,
        "events": [dict(event) for event in conn.execute(events).mappings()],
        "evaluations": [dict(run) for run in conn.execute(evaluations).mappings()],
        "spent": spending.spent(conn, row["round_id"]),
    }


def listing(conn: Connection) -> list[dict[str, Any]]:
    """Every round, newest first."""
    query = select(rounds).order_by(rounds.c.round_id.desc())
    return [describe(conn, row) for row in conn.execute(query).mappings().all()]


def record_usage(conn: Connection, round_id: int, reply: dict[str, Any]) -> None:
    """Record one of the improver's model replies with its round, once per key."""
    conn.execute(
        insert(db.usage)
        .values(round_id=round_id, claim_id=None, run_id=None, **reply)
        .on_conflict_do_nothing()
    )
