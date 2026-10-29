# Status

The claims pilot from `docs/PLAN.md` is built: all 7 phases are done. The harness from `docs/HARNESS.md` is being built to `docs/PLAN_HARNESS.md`: phases 1 (the codebase split), 2 (the manual and the wording by section) 3 (failures put right), 4 (one run works the queue) and 5 (the dashboard) are done.

## What's built

- `backend/`: FastAPI on SQLite. `backend/api.py` builds the app from the routers in `backend/routes/` (claims, runs, and the library of wording, instructions and handlers); `backend/rules.py` holds the claim states and the approval limit, and `backend/db.py` the schema and the seed. On first start it creates `undercover.db` and seeds it from `data/` (never `data/evals/`). Set `UNDERCOVER_DB` to use another file. `uv run -m backend.seed` starts again from `data/`.
  - Read: the queue, a claim in full (its policy, plan, the customer's name and claim history, the decision and the payment), the agent's steps, the policy wording, the sections of the wording and the claims manual and a search across them (`/api/documents/...`), the agent's instructions (`backend/instructions/claim.md`) and the handlers.
  - Failures: each failed attempt is counted on the claim. The first sends it back to `waiting`, the second leaves it `needs_handler` (Left for a handler). On startup the backend fails any claim a crash left `in_progress`, so none stays stuck.
  - The rules: start a claim, record the decision, pay it and sign it off. An approval over $800 (`payout_approval_limit` in `data/company.json`) waits for a handler's sign-off, and the backend refuses the payment until then, whatever the agent does.
  - Running the agent: `POST /api/claims/{id}/run` on one claim, or `POST /api/runs` with a cap for a queue run. A run is a record (`GET /api/runs/current`): its cap, the number of claims it will work, the claims in the order the agent took them, the agent's to-do list and its summary. The backend holds the run to its cap, and refuses to let it finish while a claim within the cap is still waiting.
- `agent/`: the UnderCover Agent, in two parts. The queue agent (`agent/queue.py`, instructions in `backend/instructions/queue.md`) plans a run as a to-do list, works the waiting claims in the order it chooses through `work_claim`, and finishes with a summary. `work_claim` hands each claim to the claim agent, `run(claim_id, thread_id)` in `agent/claim.py`, a subagent with a fresh thread that reports back in one line. The claim agent is on LangChain's `create_agent`, with its backend client, model and tools in their own modules. Its tools call the backend: `get_claim`, `list_sections`, `read_section` and `search_documents` (the policy wording and the claims manual a section at a time), `record_decision` and `pay_claim`. Its instructions (`backend/instructions/claim.md`) come from the backend, and its middleware (`agent/middleware.py`) records each step on the claim, with each section it reads as a `read` step. It uses `deepseek/deepseek-v4.1-flash` with low effort and a 120-second timeout, or the model in `MODEL_NAME`. Provider errors are retried twice, a claim stops after 30 model calls, and whatever goes wrong, the run fails the claim and reports back in one line instead of raising.
- `dashboard/`: React in UnderCover's brand, light and dark.
  - `#/`: the queue, with a count of claims in each state (Left for a handler included), "Run the queue" with "Claims in this run" (all the waiting claims by default; 5 for a trial), "Watch live", and the current run's to-do list, ticked off as the agent goes, then the agent's summary.
  - `#/claims/CLM-1001`: a claim in full, with its decision, "What the agent read" (the sections it opened, in order), its failed attempts, the agent's steps as they arrive, "Run the agent" and sign-off.
  - `#/live`: the live view. It goes full screen, follows the claim the agent is on, stamps each outcome (Approved, Declined, Referred, Waiting for sign-off, Left for a handler), moves on to the next claim and ends on a summary with the agent's own. A claim sent back to the queue leaves without a stamp. Esc leaves. Its numbers ("Claim 4 of 5", the tally and the summary) come from the run record in the backend, so they're the same if it's opened part way through a run or after one. Screenshots are in `docs/screenshots/`.
  - `#/instructions`: the agent's instructions, read only: working the queue and working a claim.
- `e2e/`: Playwright tests of the queue, a claim, the sign-off rule, the live view and the instructions. They run on their own ports (backend 8001, dashboard 5174) with a fresh database in the temp folder, so they never touch `undercover.db`, and they record decisions through the API in place of a model.

## How to run it

```
uv sync
npm install
npm run dev
```

Then open http://localhost:5173. The backend is on port 8000. `OPENROUTER_API_KEY` must be in `.env` for the agent.

- One claim: "Run the agent" on the claim's page, or `uv run -m agent CLM-1001` while the backend is running.
- A queue run from the command line: `uv run -m agent --cap 5` while the backend is running.
- The whole queue: "Run the queue" on the queue page. A full run with `gpt-6-luna` took 6.5 minutes and costs about a cent.
- `npm run check` runs every check.
