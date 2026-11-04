"""Run the claim agent on one claim here, with the backend running.

uv run -m agent CLM-1001  work one claim, or carry it on if it stopped
"""

import sys

from dotenv import load_dotenv

from agent import claim

load_dotenv(override=True)
print(claim.work(sys.argv[1], None))
