# Status

The claims pilot, being built from `docs/PLAN.md`. Phases 1 to 6 of 7 are done.

- `backend/`: FastAPI on SQLite. On first start it creates `undercover.db` and seeds it from `data/` (never `data/evals/`); set `UNDERCOVER_DB` to use another file. Delete the file to start again from the seed. Read-only routes for the queue, a claim in full, the policy wording, the agent's instructions (`backend/instructions.md`) and the handlers. Routes to start a claim, record the agent's steps and decision, pay a claim and sign off: an approval over $800 waits for a handler's sign-off, and the payment is refused until then.
- `agent/`: the UnderCover Agent, `run(claim_id, thread_id)`, with four tools that call the backend: `get_claim`, `get_policy_wording`, `record_decision` and `pay_claim`. Its instructions come from the backend, and it posts each step as it works. It uses `openai/gpt-6-luna` with low effort, or `MODEL_NAME`. Run it on one claim with `uv run -m agent CLM-1001` while the backend is running, or with `POST /api/claims/{id}/run`.
- `dashboard/`: React in UnderCover's brand, light and dark. The queue (`#/`) with a count of claims in each state; a claim in full (`#/claims/CLM-1001`) with its decision, the agent's steps as they arrive, "Run the agent" and sign-off; the live view (`#/live`), full screen, which follows the claim the agent is on, stamps each outcome, moves on to the next and ends on a summary; and the agent's instructions, read only (`#/instructions`). "Run the queue" (`POST /api/queue/run`) runs the agent on every waiting claim in turn.
- `e2e/`: Playwright tests of the queue and the instructions. They run on their own ports (backend 8001, dashboard 5174) with a fresh database in the temp folder, so they never touch `undercover.db`.

`npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173.
