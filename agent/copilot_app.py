"""The UnderCover Copilot as an AgentCore app of its own, the same on a laptop and on
Runtime.

npm run dev serves it with uvicorn on 127.0.0.1:8081; on Runtime, runtime/copilot.py
runs it. Each payload names an operation: a turn of a conversation, the handler's
answer to a confirmation, or a health check. A turn or an answer first asks the app
who is signed in, and ends there if the app doesn't accept the sign-in. Otherwise it
answers at once and works on a thread of its own, registered as an async task, so
its Runtime session lasts as long as the turn.

Off Runtime it asks for no key: everything it does carries the handler's sign-in,
which the app checks. Payloads carry the sign-in, so nothing here logs one.
"""

import logging
import threading
from collections.abc import Callable
from typing import Annotated, Any, Literal

from bedrock_agentcore import BedrockAgentCoreApp
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException

from agent import copilot_client, copilot_graph, memory, ready
from agent.copilot_client import Refused
from agent.copilot_tools import CopilotContext

REASON_LENGTH = 300
log = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


class Operation(BaseModel):
    """A payload: the operation and its inputs, none of them optional."""

    model_config = ConfigDict(extra="forbid")


class Health(Operation):
    """Check that the Copilot is ready."""

    operation: Literal["health"]


class Turn(Operation):
    """A handler's message on a conversation, with their sign-in."""

    operation: Literal["turn"]
    conversation_id: str
    turn_id: int
    message: str
    token: str


class Answer(Operation):
    """The handler's answer to the confirmation a turn waits on, with their sign-in."""

    operation: Literal["answer"]
    conversation_id: str
    turn_id: int
    confirmed: bool
    token: str


Payload = Annotated[Health | Turn | Answer, Field(discriminator="operation")]
PAYLOAD = TypeAdapter[Payload](Payload)


def spawn(work: Callable[[], object]) -> None:
    """Run work on a thread of its own."""
    threading.Thread(target=work, daemon=True).start()


def short(error: Exception) -> str:
    """A short reason for the sidebar."""
    text = str(error) or type(error).__name__
    return text[:REASON_LENGTH]


def in_background(context: CopilotContext, work: Callable[[], object]) -> None:
    """Register the turn as an async task, so Runtime's session lasts as long as it,
    and run it on its own thread. A turn that fails tells the app why."""
    task = app.add_async_task("turn")

    def run() -> None:
        try:
            work()
        except Exception as error:
            log.exception("Turn %s failed", context.turn_id)
            path = copilot_graph.turn_path(context)
            try:
                copilot_client.call(
                    context.token, "POST", f"{path}/fail", {"reason": short(error)}
                )
            except Exception:
                log.exception(
                    "The app didn't hear that turn %s failed", context.turn_id
                )
        finally:
            app.complete_async_task(task)

    spawn(run)


def context_for(asked: Turn | Answer) -> CopilotContext:
    """Who the Copilot works for on this turn, as the app says from the sign-in."""
    handler = copilot_client.call(asked.token, "GET", "/api/me")
    return CopilotContext(
        token=asked.token,
        handler=handler,
        conversation_id=asked.conversation_id,
        turn_id=asked.turn_id,
        memory=memory.for_copilot(),
    )


def operate(asked: Payload) -> dict[str, Any]:
    """Do the operation a payload names, and answer at once."""
    if isinstance(asked, Health):
        return {"healthy": True}
    try:
        context = context_for(asked)
    except Refused as refused:
        return {"refused": f"The app didn't accept the sign-in: {refused.detail}"}
    if isinstance(asked, Turn):
        message = asked.message
        in_background(context, lambda: copilot_graph.turn(context, message))
    else:
        confirmed = asked.confirmed
        in_background(context, lambda: copilot_graph.answer(context, confirmed))
    return {"accepted": True}


def parse(payload: Any) -> Payload:
    """Read a payload, or refuse it with a 400 saying what's wrong, never what was
    sent, which may hold a sign-in."""
    try:
        return PAYLOAD.validate_python(payload)
    except ValidationError as invalid:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'payload'}: "
            f"{error['msg']}"
            for error in invalid.errors()
        )
        raise HTTPException(400, problems) from None


@app.entrypoint
def invoke(payload: Any) -> dict[str, Any]:
    """The Copilot's one entrypoint: get ready, then do the operation."""
    asked = parse(payload)
    ready.get_copilot_ready()
    return operate(asked)
