"""Run the UnderCover Agent on one claim: uv run -m agent CLM-1001."""

import sys
import uuid

from agent.claim import run

claim_id = sys.argv[1]
print(run(claim_id, f"{claim_id}-{uuid.uuid4().hex[:8]}"))
