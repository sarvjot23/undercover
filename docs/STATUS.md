# Status

The claims pilot, being built from `docs/PLAN.md`. Phase 1 of 7 is done.

- `backend/`: FastAPI on SQLite. On first start it creates `undercover.db` and seeds it from `data/` (never `data/evals/`); set `UNDERCOVER_DB` to use another file. Delete the file to start again from the seed. Read-only routes for the queue, a claim in full, the policy wording, the agent's instructions (`backend/instructions.md`) and the handlers.
- `agent/`: still the skeleton's entry point `run(claim_id, thread_id)`.
- `dashboard/`: still the skeleton's health page.
- `e2e/`: one test of that page.

`npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173.
