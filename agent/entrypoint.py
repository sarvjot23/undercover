"""The UnderCover Agent as an AgentCore app, the same on a laptop and on Runtime.

npm run dev serves it with uvicorn on port 8080; on Runtime, runtime/main.py runs it.
Each payload names an operation and carries its inputs. An operation checks what it
must, registers its work with the AgentCore app as an async task, answers at once and
works on a thread of its own, so /ping says HealthyBusy until the work is done. The
app creates runs and rounds and keeps one piece of work at a time: on Runtime each
session is a process of its own.
"""

import logging
import os
import secrets
import threading
from collections.abc import Callable
from typing import Annotated, Any, Literal

from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException

from agent import (
    claim,
    client,
    dispatcher,
    graph,
    improver_client,
    lease,
    ready,
    rounds,
    tracing,
)

NO_KEY = "The agent's key is missing or wrong"
FAILED = "The agent's work on it failed"
log = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


class Refused(Exception):
    """The agent won't take this work, and says why."""


class Operation(BaseModel):
    """A payload: the operation and its inputs, none of them optional."""

    model_config = ConfigDict(extra="forbid")


class Health(Operation):
    """Check that the agent is ready."""

    operation: Literal["health"]


class WorkRun(Operation):
    """Work a dispatch or an evaluation the app has created."""

    operation: Literal["work_run"]
    run_id: int


class WorkRound(Operation):
    """Work a round of improvement the app has opened: its first evaluations, then
    the improver."""

    operation: Literal["work_round"]
    round_id: int


class CarryRoundOn(Operation):
    """Carry a round on after a handler's review of its proposal, which the app
    recorded."""

    operation: Literal["carry_round_on"]
    round_id: int
    proposal_id: int


class StopRound(Operation):
    """Note a round stopped by a handler: its work checks before each claim and call."""

    operation: Literal["stop_round"]
    round_id: int


class WorkClaim(Operation):
    """Start the agent on one waiting claim, on this thread."""

    operation: Literal["work_claim"]
    claim_id: str
    thread_id: str


class ResumeClaim(Operation):
    """Resume a paused claim with the handler's answer, from the app's record."""

    operation: Literal["resume_claim"]
    claim_id: str


Payload = Annotated[
    Health | WorkRun | WorkRound | CarryRoundOn | StopRound | WorkClaim | ResumeClaim,
    Field(discriminator="operation"),
]
PAYLOAD = TypeAdapter[Payload](Payload)


def spawn(work: Callable[[], object]) -> None:
    """Run work on a thread of its own."""
    threading.Thread(target=work, daemon=True).start()


def in_background(name: str, work: Callable[[], object]) -> None:
    """Register the work as an async task, so Runtime's session lasts as long as it,
    and run it on its own thread; the task is completed however the work ends."""
    task = app.add_async_task(name)

    def run() -> None:
        try:
            work()
        except Exception:
            log.exception("%s failed", name)
        finally:
            app.complete_async_task(task)

    spawn(run)


def work_run(run_id: int) -> None:
    """Work a running dispatch or evaluation, telling the app every minute; if the
    work fails, only this run is stopped."""
    with client.backend() as backend:
        found = backend.get(f"/api/runs/{run_id}").json()
    if found["status"] != "running":
        raise Refused(f"Run {run_id} is {found['status']}")
    run: tracing.Run = {
        "run_id": run_id,
        "kind": found["kind"],
        "version": found["version"],
        "round_id": found["round_id"],
    }

    def work() -> None:
        with lease.reporting(f"/api/runs/{run_id}/heard"):
            dispatcher.dispatch(run, found["n"])

    in_background(found["kind"], work)


def open_round(round_id: int) -> None:
    """Refuse a round that isn't open."""
    found = improver_client.find(round_id)
    if found["status"] not in ("working", "waiting"):
        raise Refused(f"Round {round_id} is {found['status']}")


def work_round(round_id: int, stretch: Callable[[], None]) -> None:
    """Do a stretch of a round's work in the background, telling the app every
    minute. If it breaks, only this round is stopped, with its running evaluation."""
    open_round(round_id)

    def work() -> None:
        with lease.reporting(f"/api/rounds/{round_id}/heard"):
            try:
                stretch()
            except Exception:
                if improver_client.find(round_id)["status"] == "working":
                    improver_client.halt(round_id, FAILED)
                raise

    in_background("round", work)


def carry_round_on(round_id: int, proposal_id: int) -> None:
    """Carry the improver on with the handler's review, read from the app."""
    review = improver_client.review(round_id, proposal_id)
    work_round(
        round_id,
        lambda: rounds.resume(round_id, review["decision"], review["message"]),
    )


def resume_claim(claim_id: str) -> None:
    """Resume a paused claim with the handler's answer, outside any run, beside any
    other work. A sent-back claim is taken first: only the first caller gets it."""
    worker = None
    found = graph.standing(claim_id)
    if found["status"] == "sent_back":
        worker = claim.take(claim_id)
        if worker is None:
            raise Refused(f"Claim {claim_id} was taken by another worker")
    elif found["sign_off"] is None or not claim.paused(claim_id):
        raise Refused(f"Claim {claim_id} isn't paused with an answer")
    in_background("claim", lambda: claim.carry_on(claim_id, None, None, worker))


def operate(asked: Payload) -> dict[str, Any]:
    """Do the operation a payload names, and answer at once."""
    match asked:
        case Health():
            return {"healthy": True}
        case WorkRun(run_id=run_id):
            work_run(run_id)
        case WorkRound(round_id=round_id):
            work_round(round_id, lambda: rounds.work(round_id))
        case CarryRoundOn(round_id=round_id, proposal_id=proposal_id):
            carry_round_on(round_id, proposal_id)
        case StopRound():
            pass
        case WorkClaim(claim_id=claim_id, thread_id=thread_id):
            in_background("claim", lambda: claim.run(claim_id, thread_id))
        case ResumeClaim(claim_id=claim_id):
            resume_claim(claim_id)
    return {"accepted": True}


def parse(payload: Any) -> Payload:
    """Read a payload, or refuse it with a 400 saying what's wrong."""
    try:
        return PAYLOAD.validate_python(payload)
    except ValidationError as invalid:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'payload'}: "
            f"{error['msg']}"
            for error in invalid.errors()
        )
        raise HTTPException(400, problems) from None


def check_key(context: RequestContext | None) -> None:
    """Off Runtime, refuse a request without the agent's key with a 401. On Runtime,
    AWS checks the caller may invoke the runtime before a request gets here."""
    if ready.on_runtime():
        return
    headers = (context.request_headers if context else None) or {}
    expected = f"Bearer {os.environ['UNDERCOVER_API_KEY']}"
    if not secrets.compare_digest(headers.get("Authorization", ""), expected):
        raise HTTPException(401, NO_KEY)


@app.entrypoint
def invoke(payload: Any, context: RequestContext) -> dict[str, Any]:
    """The agent's one entrypoint: get ready, check the key, then do the operation."""
    asked = parse(payload)
    ready.get_ready()
    if not isinstance(asked, Health):
        check_key(context)
    try:
        return operate(asked)
    except Refused as refused:
        return {"refused": str(refused)}
