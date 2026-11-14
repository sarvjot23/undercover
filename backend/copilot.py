"""The Copilot's conversations: each its handler's alone, one turn at a time.

A turn is working, waiting for a confirmation, done, failed or stopped. One still
working 20 minutes after it started, or after the handler answered its confirmation,
reads as stopped, and a new message marks it so. A waiting turn is never stopped.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, select

from backend import db
from backend.db import conversations, copilot_steps, copilot_turns

STOPPED_AFTER = timedelta(minutes=20)
TITLE_LENGTH = 80
STILL_WORKING = "The Copilot is still working on your last message"
ANSWER_FIRST = "Answer the confirmation first"
NOTHING_WAITING = "No confirmation is waiting"
NOT_WORKING = "This turn isn't working"
STOPPED = "The Copilot stopped answering"


def new_id() -> str:
    """A conversation's id: 37 letters, digits and hyphens, which suits both a
    Runtime session and a Memory session."""
    return f"conv-{uuid.uuid4().hex}"


def title_of(message: str) -> str:
    """A conversation's title: its first question, cut short if it's long."""
    line = " ".join(message.split())
    if len(line) <= TITLE_LENGTH:
        return line
    return line[: TITLE_LENGTH - 1].rstrip() + "…"


def find(conn: Connection, conversation_id: str, handler_id: str) -> RowMapping:
    """The handler's own conversation, or 404: nobody sees another's."""
    query = select(conversations).where(
        conversations.c.conversation_id == conversation_id,
        conversations.c.handler_id == handler_id,
    )
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"No conversation {conversation_id}")
    return row


def find_turn(conn: Connection, conversation_id: str, turn_id: int) -> RowMapping:
    """A turn of this conversation, or 404."""
    query = select(copilot_turns).where(
        copilot_turns.c.turn_id == turn_id,
        copilot_turns.c.conversation_id == conversation_id,
    )
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"No turn {turn_id}")
    return row


def stale(turn: RowMapping) -> bool:
    """Whether a working turn has gone 20 minutes since it started or was answered."""
    since = datetime.fromisoformat(turn["answered_at"] or turn["started_at"])
    return datetime.fromisoformat(db.now()) - since > STOPPED_AFTER


def status_of(turn: RowMapping) -> str:
    """Where a turn stands, with a working turn gone quiet read as stopped."""
    if turn["status"] == "working" and stale(turn):
        return "stopped"
    return turn["status"]


def start(conn: Connection, handler_id: str, message: str) -> str:
    """Start a conversation, titled with its first message."""
    conversation_id = new_id()
    conn.execute(
        conversations.insert().values(
            conversation_id=conversation_id,
            handler_id=handler_id,
            title=title_of(message),
            started_at=db.now(),
        )
    )
    return conversation_id


def start_turn(conn: Connection, conversation: RowMapping, message: str) -> int:
    """Record a new turn as working, or refuse with a 409 while one works or waits.

    The conversation's working turn moves only from what was read, so of two
    messages at once only one starts a turn.
    """
    current = conversation["working_turn"]
    if current is not None:
        turn = find_turn(conn, conversation["conversation_id"], current)
        if turn["status"] == "waiting":
            raise HTTPException(409, ANSWER_FIRST)
        if turn["status"] == "working":
            if not stale(turn):
                raise HTTPException(409, STILL_WORKING)
            end(conn, turn, status="stopped", error=STOPPED)
            current = None
    turn_id = conn.execute(
        copilot_turns.insert().values(
            conversation_id=conversation["conversation_id"],
            message=message,
            status="working",
            started_at=db.now(),
        )
    ).inserted_primary_key[0]  # type: ignore[index]
    held = conversations.c.working_turn
    moved = conn.execute(
        conversations.update()
        .where(
            conversations.c.conversation_id == conversation["conversation_id"],
            held.is_(None) if current is None else held == current,
        )
        .values(working_turn=turn_id)
    )
    if moved.rowcount != 1:
        raise HTTPException(409, STILL_WORKING)
    return turn_id


def end(conn: Connection, turn: RowMapping, **values: Any) -> None:
    """End a turn, and free its conversation for the next message."""
    conn.execute(
        copilot_turns.update()
        .where(copilot_turns.c.turn_id == turn["turn_id"])
        .values(ended_at=db.now(), **values)
    )
    conn.execute(
        conversations.update()
        .where(conversations.c.working_turn == turn["turn_id"])
        .values(working_turn=None)
    )


def working(conn: Connection, conversation_id: str, turn_id: int) -> RowMapping:
    """A turn the Copilot is still working on, or 409."""
    turn = find_turn(conn, conversation_id, turn_id)
    if turn["status"] != "working":
        raise HTTPException(409, NOT_WORKING)
    return turn


def pause(conn: Connection, turn_id: int, confirmation: dict[str, Any]) -> None:
    """Keep the confirmation the turn waits on until the handler answers it."""
    conn.execute(
        copilot_turns.update()
        .where(copilot_turns.c.turn_id == turn_id)
        .values(status="waiting", confirmation=confirmation, confirmed=None)
    )


def answer(conn: Connection, conversation: RowMapping, confirmed: bool) -> int:
    """Move the waiting turn back to working with the handler's answer, once."""
    turn_id = conversation["working_turn"]
    if turn_id is None:
        raise HTTPException(409, NOTHING_WAITING)
    moved = conn.execute(
        copilot_turns.update()
        .where(
            copilot_turns.c.turn_id == turn_id,
            copilot_turns.c.status == "waiting",
        )
        .values(status="working", answered_at=db.now(), confirmed=confirmed)
    )
    if moved.rowcount != 1:
        raise HTTPException(409, NOTHING_WAITING)
    return turn_id


def record_step(conn: Connection, turn_id: int, key: str, step: dict[str, Any]) -> None:
    """Record a step once by its key, then update it as it changes."""
    where = (copilot_steps.c.turn_id == turn_id) & (copilot_steps.c.key == key)
    updated = conn.execute(copilot_steps.update().where(where).values(**step))
    if updated.rowcount == 0:
        conn.execute(
            copilot_steps.insert().values(
                turn_id=turn_id, key=key, started_at=db.now(), **step
            )
        )


def listed(conn: Connection, handler_id: str) -> list[dict[str, Any]]:
    """The handler's conversations, newest first."""
    query = (
        select(conversations)
        .where(conversations.c.handler_id == handler_id)
        .order_by(conversations.c.started_at.desc(), conversations.c.conversation_id)
    )
    return [
        {k: v for k, v in row.items() if k != "working_turn"}
        for row in conn.execute(query).mappings()
    ]


def described(conn: Connection, conversation: RowMapping) -> dict[str, Any]:
    """A conversation with each turn and its steps, in order."""
    conversation_id = conversation["conversation_id"]
    turns = (
        conn.execute(
            select(copilot_turns)
            .where(copilot_turns.c.conversation_id == conversation_id)
            .order_by(copilot_turns.c.turn_id)
        )
        .mappings()
        .all()
    )
    found = (
        conn.execute(
            select(copilot_steps)
            .where(copilot_steps.c.turn_id.in_([turn["turn_id"] for turn in turns]))
            .order_by(copilot_steps.c.step_id)
        )
        .mappings()
        .all()
    )
    return {
        "conversation_id": conversation_id,
        "title": conversation["title"],
        "started_at": conversation["started_at"],
        "turns": [
            {
                **turn,
                "status": status_of(turn),
                "steps": [dict(s) for s in found if s["turn_id"] == turn["turn_id"]],
            }
            for turn in turns
        ],
    }
