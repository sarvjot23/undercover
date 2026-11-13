"""The improver's connection to the backend: its round, the results it reads, and
its spending. The claim agent's client, agent/client.py, reaches none of this."""

from typing import Any

from agent import client


class Refused(Exception):
    """The backend refused a round's request, saying why."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Send a request about a round; a refusal raises, with the backend's reason."""
    with client.backend() as backend:
        response = backend.request(method, path, json=body)
    if not response.is_success:
        raise Refused(response.status_code, str(response.json().get("detail", "")))
    return response.json()


def rounds(round_id: int) -> str:
    """The address of a round."""
    return f"/api/rounds/{round_id}"


def find(round_id: int) -> dict[str, Any]:
    """A round as the backend records it."""
    return call("GET", rounds(round_id))


def open_round() -> dict[str, Any] | None:
    """The round that is open, if there is one."""
    return call("GET", "/api/rounds/open")


def instructions(round_id: int) -> str:
    """The improver's instructions, around the round's recipe."""
    return call("GET", f"{rounds(round_id)}/instructions")["instructions"]


def view(round_id: int) -> dict[str, Any]:
    """What the improver reads: the current version, its scores and its mistakes."""
    return call("GET", f"{rounds(round_id)}/view")


def first_evaluations(round_id: int) -> dict[str, Any]:
    """The current version's whole-set evaluations still missing."""
    return call("GET", f"{rounds(round_id)}/first-evaluations")


def spending(round_id: int) -> dict[str, Any]:
    """The round's limit, what it has spent, what's left and whether it's open."""
    return call("GET", f"{rounds(round_id)}/spending")


def may_go_on(round_id: int) -> bool:
    """Whether a round is still open and has something left to spend."""
    found = spending(round_id)
    return found["open"] and found["left"] > 0


def progress(round_id: int, stage: str, step: str | None) -> None:
    """Record where the round has got to."""
    call("POST", f"{rounds(round_id)}/progress", {"stage": stage, "progress": step})


def propose(round_id: int, kind: str, proposal: dict[str, Any]) -> None:
    """Record a proposal waiting for a handler: a change or a recipe."""
    call("POST", f"{rounds(round_id)}/proposals/{kind}", proposal)


def review(round_id: int, proposal_id: int) -> dict[str, Any]:
    """A handler's review of a proposal, as the app recorded it: the decision and
    the reason."""
    return call("GET", f"{rounds(round_id)}/reviews/{proposal_id}")


def judge(round_id: int, unaffordable: bool) -> dict[str, Any]:
    """Ask the backend to keep the version tried or roll it back."""
    return call("POST", f"{rounds(round_id)}/verdict", {"unaffordable": unaffordable})


def finish(round_id: int) -> None:
    """Mark the round finished."""
    call("POST", f"{rounds(round_id)}/finish")


def halt(round_id: int, reason: str) -> None:
    """Mark a round whose work failed as stopped, with its running evaluation."""
    call("POST", f"{rounds(round_id)}/halt", {"reason": reason})


def create_evaluation(round_id: int, version: int, set_name: str, n: int) -> Any:
    """Create one of the round's whole-set evaluations of a version."""
    body = {
        "kind": "evaluation",
        "n": n,
        "set_name": set_name,
        "tiny": False,
        "version": version,
        "round_id": round_id,
    }
    return call("POST", "/api/runs", body)


def run_status(run_id: int) -> str:
    """Whether an evaluation finished or was stopped."""
    return call("GET", f"/api/runs/{run_id}")["status"]


def models_allowed() -> list[dict[str, Any]]:
    """The models the claim agent may use."""
    return call("GET", "/api/settings")["models"]


def record_usage(round_id: int, reply: dict[str, Any]) -> None:
    """Record one of the improver's replies, with its round."""
    with client.backend() as backend:
        backend.post(f"{rounds(round_id)}/usage", json=reply)
