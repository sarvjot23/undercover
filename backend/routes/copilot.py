"""The Copilot's conversations: the handler's routes for the sidebar, and the
Copilot's own, which carry the same handler's sign-in.

The app sends each turn to the Copilot with the sign-in the handler sent, and saves
it nowhere.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, RowMapping

from backend import copilot, copilot_service
from backend.auth import Credentials, SignedIn
from backend.db import Db, SingleStatementDb
from backend.schemas import (
    CopilotConfirmation,
    CopilotMessage,
    CopilotStep,
    TurnFailure,
    TurnFinish,
    TurnPause,
)

router = APIRouter(prefix="/api/conversations")


def sign_in(handler: SignedIn, credentials: Credentials) -> tuple[dict[str, Any], str]:
    """The handler signed in and the sign-in itself, to pass on to the Copilot."""
    assert credentials is not None  # noqa: S101 - signed_in has checked it
    return handler, credentials.credentials


SignIn = Annotated[tuple[dict[str, Any], str], Depends(sign_in)]


def ask_copilot(
    conn: Connection, conversation_id: str, turn_id: int, payload: dict[str, Any]
) -> None:
    """Send the Copilot a turn or an answer; one it didn't take fails the turn, so
    the handler can carry on."""
    answer = copilot_service.send(conversation_id, payload)
    if answer.outcome in ("accepted", "unknown"):
        return
    turn = copilot.find_turn(conn, conversation_id, turn_id)
    copilot.end(conn, turn, status="failed", error=answer.detail)
    conn.commit()


def send_turn(
    conn: Connection, conversation_id: str, handler_id: str, message: str, token: str
) -> dict[str, Any]:
    """Record a new turn as working, commit it, then send it to the Copilot."""
    conversation = copilot.find(conn, conversation_id, handler_id)
    turn_id = copilot.start_turn(conn, conversation, message)
    conn.commit()
    payload = {
        "operation": "turn",
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "message": message,
        "token": token,
    }
    ask_copilot(conn, conversation_id, turn_id, payload)
    return copilot.described(conn, copilot.find(conn, conversation_id, handler_id))


@router.post("", operation_id="start_conversation", status_code=202)
def start_conversation(
    sent: CopilotMessage, signed: SignIn, conn: Db
) -> dict[str, Any]:
    """Start a conversation with the Copilot with its first message."""
    handler, token = signed
    conversation_id = copilot.start(conn, handler["handler_id"], sent.message)
    return send_turn(conn, conversation_id, handler["handler_id"], sent.message, token)


@router.get("", operation_id="list_conversations")
def list_conversations(
    handler: SignedIn, conn: SingleStatementDb
) -> list[dict[str, Any]]:
    """List the handler's own conversations, newest first."""
    return copilot.listed(conn, handler["handler_id"])


@router.get("/{conversation_id}", operation_id="get_conversation")
def get_conversation(
    conversation_id: str, handler: SignedIn, conn: SingleStatementDb
) -> dict[str, Any]:
    """Get one of the handler's conversations with each turn and its steps."""
    conversation = copilot.find(conn, conversation_id, handler["handler_id"])
    return copilot.described(conn, conversation)


@router.post(
    "/{conversation_id}/messages", operation_id="send_message", status_code=202
)
def send_message(
    conversation_id: str, sent: CopilotMessage, signed: SignIn, conn: Db
) -> dict[str, Any]:
    """Send the Copilot a message, unless it's still working on the last one."""
    handler, token = signed
    return send_turn(conn, conversation_id, handler["handler_id"], sent.message, token)


@router.post(
    "/{conversation_id}/confirmation",
    operation_id="answer_confirmation",
    status_code=202,
)
def answer_confirmation(
    conversation_id: str, answer: CopilotConfirmation, signed: SignIn, conn: Db
) -> dict[str, Any]:
    """Answer the confirmation waiting: sign off and pay, or cancel."""
    handler, token = signed
    conversation = copilot.find(conn, conversation_id, handler["handler_id"])
    turn_id = copilot.answer(conn, conversation, answer.confirmed)
    conn.commit()
    payload = {
        "operation": "answer",
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "confirmed": answer.confirmed,
        "token": token,
    }
    ask_copilot(conn, conversation_id, turn_id, payload)
    return copilot.described(conn, conversation)


def own_turn(
    conversation_id: str, turn_id: int, handler: SignedIn, conn: Db
) -> RowMapping:
    """A working turn of the handler's own conversation, or 404 or 409."""
    copilot.find(conn, conversation_id, handler["handler_id"])
    return copilot.working(conn, conversation_id, turn_id)


# The request's connection is the same one own_turn read through: FastAPI gives a
# request one of each dependency.
Turn = Annotated[RowMapping, Depends(own_turn)]
# The Copilot's own routes, each on a turn it's working.
turns = APIRouter(prefix="/api/conversations/{conversation_id}/turns/{turn_id}")


@turns.put(
    "/steps/{key}",
    operation_id="record_copilot_step",
)
def record_copilot_step(
    key: str, step: CopilotStep, turn: Turn, conn: Db
) -> dict[str, str]:
    """Record one of the Copilot's steps as its card shows it, once by its key."""
    copilot.record_step(conn, turn["turn_id"], key, step.model_dump())
    conn.commit()
    return {"key": key}


@turns.post("/finish", operation_id="finish_turn")
def finish_turn(finished: TurnFinish, turn: Turn, conn: Db) -> dict[str, Any]:
    """Record the Copilot's answer, with the turn's model calls and their cost."""
    copilot.end(conn, turn, status="done", confirmation=None, **finished.model_dump())
    conn.commit()
    return {"turn_id": turn["turn_id"], "status": "done"}


@turns.post("/pause", operation_id="pause_turn")
def pause_turn(paused: TurnPause, turn: Turn, conn: Db) -> dict[str, Any]:
    """Keep the confirmation the Copilot waits on until the handler answers it."""
    copilot.pause(conn, turn["turn_id"], paused.confirmation)
    conn.commit()
    return {"turn_id": turn["turn_id"], "status": "waiting"}


@turns.post("/fail", operation_id="fail_turn")
def fail_turn(failure: TurnFailure, turn: Turn, conn: Db) -> dict[str, Any]:
    """Record why a turn failed, so the handler can carry on."""
    copilot.end(conn, turn, status="failed", error=failure.reason)
    conn.commit()
    return {"turn_id": turn["turn_id"], "status": "failed"}
