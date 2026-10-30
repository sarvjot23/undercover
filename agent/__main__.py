"""Run the UnderCover Agent, with the backend running.

uv run -m agent --cap 5   work the queue, up to 5 claims
uv run -m agent CLM-1001  work one claim
"""

import sys
import time
import uuid

from dotenv import load_dotenv

from agent import claim, client

load_dotenv(override=True)

if sys.argv[1] == "--cap":
    with client.backend() as backend:
        run = backend.post("/api/runs", json={"cap": int(sys.argv[2])}).json()
        print(f"Run {run['run_id']} started on {run['total']} claims")
        while run["status"] == "running":
            time.sleep(2)
            run = backend.get(f"/api/runs/{run['run_id']}").json()
        print(f"Run {run['run_id']} {run['status']}: {run['summary']}")
else:
    claim_id = sys.argv[1]
    print(claim.run(claim_id, f"{claim_id}-{uuid.uuid4().hex[:8]}"))
