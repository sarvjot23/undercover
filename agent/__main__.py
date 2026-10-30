"""Run the UnderCover Agent here, with the backend running.

uv run -m agent --cap 5   work the queue, up to 5 claims, or finish a run that stopped
uv run -m agent CLM-1001  work one claim, or carry it on if it stopped
"""

import sys
import uuid

from dotenv import load_dotenv

from agent import claim, client, graph, queue


def work_queue(cap: int) -> None:
    """Open a run and work it in this process."""
    with client.backend() as backend:
        response = backend.post("/api/runs/open", json={"cap": cap})
    if not response.is_success:
        sys.exit(response.json()["detail"])
    run = response.json()
    if run["resumed"]:
        print(f"Finishing run {run['run_id']}, which stopped partway")
    else:
        print(f"Run {run['run_id']} started on {run['total']} claims")
    print(queue.run(run["run_id"]))


def work_claim(claim_id: str) -> None:
    """Work one claim in this process."""
    if graph.standing(claim_id)["status"] == "in_progress":
        print(claim.carry_on(claim_id))
    else:
        print(claim.run(claim_id, f"{claim_id}-{uuid.uuid4().hex[:8]}"))


load_dotenv(override=True)
if sys.argv[1] == "--cap":
    work_queue(int(sys.argv[2]))
else:
    work_claim(sys.argv[1])
