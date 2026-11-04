# Status

The claims pilot from `docs/PLAN.md` is built (7 phases), the harness from `docs/HARNESS.md` is built to `docs/PLAN_HARNESS.md` (6 phases), and durable state from `docs/DURABLE.md` is built to `docs/PLAN_DURABLE.md` (6 phases). The swarm from `docs/SWARM.md` is being built to `docs/PLAN_SWARM.md`: phase 1 is done. The records are on Supabase. The claim agent is a LangGraph graph that waits for a handler's sign-off and carries on after a restart.

## What's built

- `backend/`: FastAPI on SQLAlchemy Core. `backend/api.py` builds the app from the routers in `backend/routes/` (claims, runs, documents, and the library of wording, instructions and handlers). `backend/rules.py` holds the claim states and the approval limit, `backend/runs.py` the rules for a run, `backend/leases.py` the leases, `backend/payout.py` the payout rules and `backend/agent_link.py` the line to the agent's service. `backend/db.py` holds the tables and the seed: Supabase's `undercover` schema when `DATABASE_URL` is set, otherwise SQLite (`undercover.db`, or the file in `UNDERCOVER_DB`). It seeds from `data/`, never `data/evals/`. `uv run -m backend.seed` starts again from `data/`.
  - Read: the queue, a claim in full (its policy, plan, the customer's name and claim history, the decision, the sign-off and the payment), where a claim stands (`/standing`, a single query, because Supabase is a round trip away), the agent's steps, the policy wording, the sections of the wording and the claims manual and a search across them (`/api/documents/...`), the agent's instructions (`backend/instructions/queue.md` and `claim.md`) and the handlers.
  - The payout rules: `POST /api/claims/{id}/payout`, with the limit from `payout_approval_limit` in `data/company.json` ($800).
  - Claim states: a decline or a referral is `decided` at once. An approval up to the limit stays `in_progress` until it's paid. An approval over the limit is `awaiting_sign_off`. A sign-off records who and when, moves it to `in_progress` and doesn't pay; the backend then calls the agent's service, and the sign-off stands if the service can't be reached. The backend refuses a payment over the limit without a sign-off, whatever the agent does, and a payment records the handler and the time.
  - Nothing happens twice: a repeat of the decision or the payment already recorded returns the claim as done, and a different one is refused. Steps have stable keys, so a restart can't show one twice.
  - Failures: an error counts an attempt, forgets the thread and sends the claim back to start afresh; the second leaves it `needs_handler` (Left for a handler). A claim with a decision can't fail: it stays in progress to be carried on. A backend restart changes nothing.
  - One worker at a time: whoever works a claim or a run holds a lease, renewed every 5 seconds. A killed worker's lease expires after 20 seconds. `POST /api/runs` and `POST /api/runs/open` refuse while a run is active, and pick up a run that stopped, keeping its cap.
- `agent/`: the UnderCover Agent, in four parts.
  - The queue agent (`agent/queue.py`, instructions in `backend/instructions/queue.md`), on `create_agent`. A run first carries on any claim that was stopped or signed off, then plans a to-do list, works the waiting claims through `work_claim` and finishes with a summary.
  - The claim agent (`agent/claim.py`, with its graph in `agent/graph.py`, instructions in `backend/instructions/claim.md`). Its nodes are `agent`, `record`, `tools`, `sign_off`, `pay` and `close`. Its tools call the backend: `get_claim`, `list_sections`, `read_section`, `search_documents`, `calculate_payout` and `record_decision`. It has no pay tool; paying is a step of the graph. `run(claim_id, thread_id)` starts a claim and `carry_on(claim_id)` picks one up. Provider errors are retried twice, and a claim stops after 30 model calls.
  - Checkpoints (`agent/checkpoints.py`): `PostgresSaver` on a pool of at most 4 connections, in memory without `DATABASE_URL`, which only the tests rely on.
  - The service (`agent/service.py`), on port 8002: start a claim, start a run, resume a signed-off claim. When it starts, it pays anything signed off while it was away.
  - The model (`agent/model.py`): `openai/gpt-6-luna` with low reasoning effort, or `MODEL_NAME` with none. Each model reply's tokens and cost, from OpenRouter's usage, go to `POST /api/claims/{id}/usage` once per reply, and each spell of work on a claim goes to `POST /api/claims/{id}/work`, stopping at a pause for a sign-off. Both carry the run, or none.
  - Tracing (`agent/tracing.py`): each claim's work is one Langfuse session, named by its thread, with traces from before and after a sign-off. There's no tracing without the keys.
- `dashboard/`: React in UnderCover's brand, light and dark.
  - `#/`: the queue, with a count of claims in each state, "Run the queue" with "Claims in this run", "Watch live", and the current run's to-do list and summary. While a run is being worked, from here or the command line, "Run the queue" is disabled with "A run is already in progress". After a run stops, it offers to finish it.
  - `#/claims/CLM-1001`: a claim in full, with its decision, "What the agent read", its failed attempts, the agent's steps as they arrive, "Run the agent" and sign-off. After a sign-off it shows in progress, then paid with the handler and the time.
  - `#/live`: the live view. It goes full screen, follows the claim the agent is on, stamps each outcome (Approved, Declined, Referred, Waiting for sign-off, Left for a handler), moves on to the next claim and ends on a summary with the agent's own. An approval is stamped once it's paid. Its numbers come from the run record in the backend. Esc leaves. Screenshots are in `docs/screenshots/`.
  - `#/instructions`: the agent's instructions, read only.
- `e2e/`: Playwright tests of the queue, a claim, the sign-off reaching the agent's service, the instructions, the run panel, one run at a time, a claim left for a handler, the sections read and the live view. They run on their own ports (backend 8001, dashboard 5174) with a fresh SQLite database, and a stand-in for the agent's service on port 8003 (`e2e/agent-standin.ts`), so they never reach Supabase or the real service. They play the agent's part through the API.

## How to run it

```
uv sync
npm install
uv run -m backend.seed
npm run dev
```

Then open http://localhost:5173. The backend is on port 8000 and the agent's service on port 8002. `.env` needs `OPENROUTER_API_KEY`, `DATABASE_URL` and the Langfuse keys. After a change to the schema, run `uv run -m backend.seed`. A SQLite file from an earlier build won't open until it's reseeded; `undercover-pilot.db` is kept as a backup only.

- One claim: "Run the agent" on the claim's page, or `uv run -m agent CLM-1001`.
- A queue run from the command line: `uv run -m agent --cap 5`, which works the run in its own process and finishes one that stopped.
- The whole queue: "Run the queue" on the queue page, with "Claims in this run" set to the number to work.
- `npm run check` runs every check, with no need for `.env`.

## The last live run

On 30 October 2026, on DeepSeek V4.1 Flash, after reseeding Supabase, with all three processes up:

- `uv run -m agent --cap 5` worked 5 claims: CLM-1001 approved and paid $420; CLM-1008 ($2,240) and CLM-1011 ($1,150) approved and waiting for sign-off; CLM-1018 referred; CLM-1010 declined. The other 20 stayed waiting.
- Signed off on the dashboard through the Playwright MCP server, CLM-1008 and CLM-1011 each showed as paid, with the handler and the time, in 3.4 seconds. Supabase is about 160 ms away, so the first sign-off straight after a restart can take about 6.5 seconds while connections warm up.
- A run killed after CLM-1001's first steps was refused a restart for 20 seconds, then carried on with the same thread, with its attempts at 0, one decision, one payment and no repeated steps.
- A claim signed off with the service stopped stayed in progress, and was paid when the service started.
- During the runs, `pg_stat_activity` showed 8 connections for user postgres, and 11 at most with the command line's process just ended, of which one is Supabase's own `pg_net`.
- Through Langfuse's API, the held claim's session had a trace from before the sign-off and one from after.

The model's payout on CLM-1011 was $1,150 in most runs and $1,330 in one, so the payout tool doesn't make every run agree. The cost wasn't measured; the Week 1 Day 5 lab puts five claims on this model at about 3 cents. Screenshots are in `docs/screenshots/durable-*.png`.
