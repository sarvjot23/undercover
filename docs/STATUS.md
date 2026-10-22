# Status

The claims pilot from `docs/PLAN.md` is built: all 7 phases are done.

## What's built

- `backend/`: FastAPI on SQLite. On first start it creates `undercover.db` and seeds it from `data/` (never `data/evals/`). Set `UNDERCOVER_DB` to use another file, and delete the file to start again from the seed.
  - Read: the queue, a claim in full (its policy, plan, the customer's name and claim history, the decision and the payment), the agent's steps, the policy wording, the agent's instructions (`backend/instructions.md`) and the handlers.
  - The rules: start a claim, record the decision, pay it and sign it off. An approval over $800 (`APPROVAL_LIMIT`) waits for a handler's sign-off, and the backend refuses the payment until then, whatever the agent does.
  - Running the agent: `POST /api/claims/{id}/run` on one claim, or `POST /api/queue/run` on every waiting claim in the order submitted, one at a time.
- `agent/`: the UnderCover Agent, `run(claim_id, thread_id)`, on LangChain's `create_agent`. Its four tools call the backend: `get_claim`, `get_policy_wording`, `record_decision` and `pay_claim`. Its instructions come from the backend, and it posts each step as it works. It uses `openai/gpt-6-luna` with low effort, or the model in `MODEL_NAME`.
- `dashboard/`: React in UnderCover's brand, light and dark.
  - `#/`: the queue, with a count of claims in each state, "Run the queue" and "Watch live".
  - `#/claims/CLM-1001`: a claim in full, with its decision, the agent's steps as they arrive, "Run the agent" and sign-off.
  - `#/live`: the live view. It goes full screen, follows the claim the agent is on, stamps each outcome (Approved, Declined, Referred, Waiting for sign-off), moves on to the next claim and ends on a summary. Esc leaves. Its numbers ("Claim 4 of 25", the tally and the summary) come from the queue run in the backend, so they're the same if it's opened part way through a run or after one. Screenshots are in `docs/screenshots/`.
  - `#/instructions`: the agent's instructions, read only.
- `e2e/`: Playwright tests of the queue, a claim, the sign-off rule, the live view and the instructions. They run on their own ports (backend 8001, dashboard 5174) with a fresh database in the temp folder, so they never touch `undercover.db`, and they record decisions through the API in place of a model.

## How to run it

```
uv sync
npm install
npm run dev
```

Then open http://localhost:5173. The backend is on port 8000. `OPENROUTER_API_KEY` must be in `.env` for the agent.

- One claim: "Run the agent" on the claim's page, or `uv run -m agent CLM-1001` while the backend is running.
- The whole queue: "Run the queue" on the queue page. A full run with `gpt-6-luna` took 6.5 minutes and costs about a cent.
- `npm run check` runs every check.
