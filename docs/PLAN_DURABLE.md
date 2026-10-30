# Plan: approvals that wait, and work that survives a restart

The plan for `docs/DURABLE.md`, on branch `week2day3-sarvjot`, made from `week1day5-sarvjot`.

SIDENOTE: For consistency with the course, please read `labs/week2day3.ipynb` and build the solution in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

## What stays ours

- **The limit stays at $800.** The brief says $1,000, but our limit is `payout_approval_limit` in `data/company.json`, and the brief says to read it from there. Nothing in the code or the tests of the new work hard-codes $1,000. `labs/week2day1_payout.py` does, so the backend's copy reads the setting instead.
- **The live view stays**, and is adapted to a claim that goes from waiting for sign-off back to in progress.
- **The code stays in small modules**, with `backend/api.py` as the app. New modules are named below.
- **The labs stay untouched.** `labs/week2day3free.ipynb` stays out of every commit.

## How it will work

### The claim's journey

| Moment | Claim status today | Claim status after this build |
|---|---|---|
| Agent is working | `in_progress` | `in_progress` |
| Decline or refer recorded | `decided` | `decided` |
| Approval up to the limit recorded | `decided` | `in_progress`, until the payment |
| Approval up to the limit paid | `decided` | `decided` |
| Approval over the limit recorded | `awaiting_sign_off` | `awaiting_sign_off`, with the graph paused |
| Handler signs off | `decided`, and paid by the backend | `in_progress`, nothing paid yet |
| The graph pays it | not applicable | `decided`, with the handler and the time on the payment |

An approval up to the limit stays in progress until it is paid. Otherwise a kill between the decision and the payment would leave a claim marked `decided` and never paid, with nothing to show it needs picking up.

### The claim graph (`agent/claim.py`, with its nodes in `agent/graph.py`)

```
START -> agent -> record -> tools -> agent ...   the model and its tools, as in the lab
                            tools -> sign_off -> pay -> close -> END    approved, over the limit
                            tools -> pay -> close -> END                approved, up to the limit
                            tools -> close -> END                       declined or referred
                  record -> END                  answered without a decision: the claim fails
```

- **State:** `messages`, `claim_id`, and a count of model calls.
- **`agent`:** calls the model and raises at 30 model calls. Provider errors are retried twice with LangGraph's `RetryPolicy` on the node.
- **`record`:** records the model's tool calls, or its answer, as steps. It's a node of its own so it runs only after the model's reply is saved in the checkpoint, and a reply lost in a crash never appears on the claim.
- **`tools`:** runs the tools, records each result (a section as a `read` step), and returns refusals to the model as text. These nodes replace `agent/middleware.py`, which goes.
- **The route after `tools`** asks the backend where the claim stands. It never compares a payout with the limit.
- **`sign_off`:** calls `interrupt()` with the claim id and payout. It holds no other work, because LangGraph runs an interrupted node again from the top on resume.
- **`pay`:** posts the payment and records it as a step. The backend refuses it without a sign-off, whatever the agent does.
- **`close`:** records the one-line report as the `answer` step. This replaces the model's closing sentence, so a resume after a sign-off costs no model call.

The claim agent loses `pay_claim` and gains `calculate_payout`. `claim.md` changes to match.

### Carrying on

The thread id is saved on the claim when it starts (`POST /api/claims/{id}/start` takes it in its body). Then:

- **A claim in progress with a thread** is carried on from its last checkpoint on that thread. The attempt count doesn't change.
- **A signed-off claim** is resumed with `Command(resume=...)`.
- **A claim that fails with an error** counts an attempt, loses its thread and goes back to the queue, so its next try starts afresh. A claim that already has a recorded decision doesn't restart; it stays in progress to be carried on, because its decision stands.
- **The backend's startup no longer fails claims left in progress.** A backend restart says nothing about the agent, and failing those claims is exactly what the brief wants to end.

### Only one worker at a time

The backend has to tell a run that's being worked from one that was killed, including when the work is in another process. So whoever works a run or a claim holds a lease on it:

- **Taking it:** a worker takes the lease with one atomic update, which only succeeds if no one else holds it. Two workers can't both win, on either database.
- **Keeping it:** a small background thread (`agent/lease.py`) renews it every 5 seconds through the backend.
- **Losing it:** a lease not renewed for 20 seconds has expired. A killed process stops renewing, so its work is free to pick up 20 seconds later. A hung process can't hold on forever, because the model's calls have a timeout.
- **What it covers:** runs and claims each have their own lease, so a sign-off resume, a named claim and a queue run can't work the same claim either.

`GET /api/runs/current` returns `active`, and what the handlers see depends on it:

| The last run | "Run the queue" | `uv run -m agent --cap 5` |
|---|---|---|
| Being worked, from the dashboard or the command line | Disabled, with "A run is already in progress" | Refused with the same message |
| Stopped, with its lease expired | Enabled, with "The last run stopped partway. Running the queue finishes it" | Finishes that run first, and says so |
| Finished or failed | Enabled, as today | Starts a new run |

The backend refuses as well as the button, with a 409, so a stale page or a second command can't get past it. Finishing a stopped run keeps that run's cap, and the number in "Claims in this run" applies to the next one.

### No repeated steps

Every step has a key that stays the same if the step runs again, and the steps table has a unique index on the claim and the key. A repeat is ignored, using the same `ON CONFLICT DO NOTHING` as decisions and payments. The keys come from the saved model message, such as `<message id>:<call number>:result`, and not from the tool call's id, because some providers reuse those between turns. `POST /api/claims/{id}/steps` takes the key as a required field.

### The processes and their connections

| Process | Started by | Connections |
|---|---|---|
| Backend, port 8000 | `npm run dev` | At most 4 (SQLAlchemy pool) |
| Agent service, port 8002 | `npm run dev` | At most 4 (checkpointer pool) |
| `uv run -m agent` | You | At most 4 (checkpointer pool) |

That's 12 at the most, the brief's limit, and within the 15 the free plan allows.

The backend stops importing the agent, because in the cloud they will be separate. It calls the service through a small `backend/agent_link.py`:

- `POST /api/runs` and `POST /api/claims/{id}/run` ask the service to do the work, as the dashboard's buttons do today.
- `POST /api/runs/open` opens a run without asking the service. `uv run -m agent --cap 5` uses it and works the run in its own process. The end-to-end tests use it too, in place of writing directly into their SQLite file.
- A sign-off saves first, then calls the service as a background task. A failed call is ignored, so the sign-off stands.

### Environment

`npm run dev` passes `.env` with `uv run --env-file .env`. The `load_dotenv` in `agent/model.py` has to move, because the backend and the tests import that module today, and it would give the tests `DATABASE_URL`. `agent/__main__.py` and `backend/seed.py` load `.env` themselves, so `uv run -m agent` and `uv run -m backend.seed` keep working as they are. A test fixture also removes `DATABASE_URL` and the Langfuse keys, in case your shell has them set.

Without `DATABASE_URL`, the backend uses SQLite and the agent uses LangGraph's in-memory checkpointer, which only the tests rely on.

## Decisions for your review

Reviewed by the student on 30 October 2026:

1. **One worker at a time.** Changed: "Run the queue" is disabled with a message while a run is being worked, and the backend refuses a second one. A killed run can be picked up 20 seconds after it stopped, not at once.
2. **Stopped claims are carried on at the start of a run, not when the service starts**, so starting `npm run dev` never spends money by itself. Signed-off claims are picked up when the service starts, because the brief asks for it and the graph has no model calls left to make.
3. **No repeated steps.** Changed: steps have stable keys, so a restart can't show one twice.
4. **Local databases.** Accepted: `undercover.db` needs a reseed, and `undercover-pilot.db` stays on disk but the dashboard can no longer read it.

## Phases

Each phase ends with its criteria ticked here, `docs/STATUS.md` updated and a commit.

### Phase 1: the payout rules and tracing

The brief asks for these first. Both work on the current agent, so they carry no risk from the later rewrite.

- `backend/payout.py`: the rules from `labs/week2day1_payout.py`, with the limit from our settings.
- `POST /api/claims/{id}/payout`, operation `calculate_payout`. It finds the policy from the claim. Every field of a line is required, because the API rules allow no optional inputs.
- The `calculate_payout` tool, and `claim.md` telling the agent to use it.
- `agent/tracing.py`: Langfuse's `CallbackHandler`, one session per claim named by its thread id (such as `CLM-1008-ab12cd34`). There are no callbacks when the keys are missing.

Success criteria:

- [ ] Tests check the payout operation: per-item limits, electronics with the add-on, cash, hotel, meals without receipts, what others paid, the deductible and the benefit maximum.
- [ ] A test shows `needs_sign_off` is true at $800.01 and false at $800.00.
- [ ] A test on a stub model shows the agent using `calculate_payout`, with the request going through the backend.
- [ ] A test shows the agent's config carries the session id when keys are set, and no callbacks when they aren't.
- [ ] A test shows importing the agent doesn't put `.env` values in the environment.
- [ ] The operation has an `operation_id`, a one-line docstring and no optional inputs (checked in `/openapi.json`).
- [ ] `npm run check:python` passes.

### Phase 2: our records on Supabase

- `backend/db.py` moves to SQLAlchemy Core: tables defined once, each query written once for both databases.
- The engine is Postgres when `DATABASE_URL` is set, using psycopg with `search_path=undercover`, `prepare_threshold=0` as in the lab, and `pool_size=2, max_overflow=2` for at most 4 connections. Otherwise it's SQLite.
- Every module with SQL (`rules.py`, `runs.py`, `routes/`) moves over with it.
- `uv run -m backend.seed` creates the schema if needed, drops our tables and seeds again. Only the `undercover` schema is touched; your lab's `lab` schema is left alone. From phase 4 it also empties the checkpointer's tables, rather than dropping them, so a running service keeps working.

Success criteria:

- [ ] All existing backend tests pass on SQLite, with no network.
- [ ] A test shows no query uses SQLite-only syntax, by compiling each table's statements for Postgres.
- [ ] `uv run -m backend.seed` runs against Supabase, twice in a row without error.
- [ ] Through the Supabase MCP server: the tables are in schema `undercover`, with 25 rows in `claims`, and nothing new in `public`.
- [ ] `npm run dev` on Supabase: `GET /api/claims` returns 25 claims and the queue page shows them, checked with the Playwright MCP server.
- [ ] `npm run check:python` passes with `.env` moved out of the way.

### Phase 3: the backend's rules for sign-offs and repeats

- A `sign_offs` table (claim, handler, time), and `signed_off_at` on `payments`, so the payment records who signed off and when.
- `sign_off` saves the sign-off, moves the claim to `in_progress` and no longer pays.
- `pay_claim` is refused over the limit without a sign-off, based on the sign-off record and not the claim's status. A successful payment moves the claim to `decided`.
- An approval up to the limit stays `in_progress` until it's paid.
- A repeat of the decision or the payment already recorded returns the claim as done. A different decision is still refused with a 409.
- The inserts use `ON CONFLICT DO NOTHING`, which reads the same on both databases, so two requests racing can't both write.
- `POST /api/claims/{id}/start` takes the thread id; `fail` clears it. `recover` leaves the backend's startup.
- `GET` on a claim and on the queue returns `thread_id` and `sign_off`.
- Leases on runs and claims: taking and renewing them, and a 409 for a second worker. `POST /api/runs` and `POST /api/runs/open` refuse while a run is active, and `GET /api/runs/current` returns `active`.
- Steps take a required key, with a unique index on the claim and the key.

Between this phase and the next, the old agent still has `pay_claim`, and a signed-off claim waits in progress until the graph exists.

Success criteria:

- [ ] Tests check a sign-off records the handler and the time, moves the claim to in progress and creates no payment.
- [ ] Tests check a payment over the limit is refused before the sign-off and accepted after, and that the payment carries the handler and the time.
- [ ] Tests check a repeated decision and a repeated payment each return the claim, leaving one row.
- [ ] Tests check a different decision and a different amount are each refused with a 409.
- [ ] Tests check a restart of the backend leaves a claim in progress, with its attempts unchanged.
- [ ] A test checks the sign-off stays saved when the claim then fails to pay.
- [ ] Tests check a lease: a second worker is refused while it's live, and allowed once it has expired, with the time moved on in the test and no waiting.
- [ ] Tests check a second run is refused with a 409 while one is active, and that a stopped run shows `active: false` once its lease has expired.
- [ ] A test checks a repeated step key leaves one row, and that the same key on another claim is a separate step.
- [ ] `npm run check:python` passes.

### Phase 4: the claim agent as a graph

- `agent/graph.py`: the hand-written state, nodes and edges above.
- `agent/lease.py`: takes a lease and keeps it renewed while the work goes on, for the queue agent and for each claim.
- `agent/checkpoints.py`: `PostgresSaver` on a pool of at most 4 connections with the lab's three settings and `search_path=undercover`, or the in-memory saver without `DATABASE_URL`. Always `durability="sync"`, on the synchronous checkpointer.
- `claim.run` starts a claim; `claim.carry_on` picks up a stopped or signed-off one. Both report back in one line and never raise.
- The queue agent stays on `create_agent`, and `queue.run` first carries on stopped claims and signed-off ones. A run that was stopped is finished by the next run, which is told the to-do list it left behind.
- `runs.end` no longer fails a signed-off claim.

Success criteria, all on a stub model:

- [ ] A test shows every step is recorded in order, including the section reads.
- [ ] A test shows a refusal goes back to the model as text.
- [ ] A test shows a claim stops at 30 model calls.
- [ ] A test shows a provider error is retried, and a run that goes on failing still fails the claim.
- [ ] A test shows an approval up to the limit is paid straight after the decision, with the model given no `pay_claim` tool.
- [ ] A test shows an approval over the limit stops at `sign_off`, with `next` naming that node and nothing paid.
- [ ] A test shows a sign-off resumes the claim and pays it once, with no further model call.
- [ ] A test stops a claim partway with an exception at the model. Carrying on uses the same thread and makes no repeat of its earlier calls, with the same attempts and one decision.
- [ ] A test stops a claim between the decision and the payment. Carrying on pays it once.
- [ ] A test shows a claim that fails with an error starts afresh on a new thread, with one more attempt.
- [ ] A test shows the second failure still leaves the claim for a handler.
- [ ] A test shows a stopped run is finished by the next, within its cap.
- [ ] A test stops a claim straight after a model reply and straight after a tool, then carries on. The claim's steps have no repeats, and no step from a reply that was lost.
- [ ] A test shows a claim with another worker's live lease isn't picked up, and that the same claim is picked up once the lease expires.
- [ ] A test shows the lease is renewed during a long step and given up at the end, with the interval shortened in the test.
- [ ] Every test in `agent/tests/test_agent.py` and `test_queue.py` that still applies passes, changed only where the brief changes the behavior.
- [ ] `npm run check:python` passes, with coverage at 80% or more.

### Phase 5: the agent's service, and the dashboard

- `agent/service.py`: FastAPI on `UNDERCOVER_AGENT` or `http://127.0.0.1:8002`, with `POST /claims/{id}/resume`, `POST /claims/{id}/run`, `POST /runs/{id}` and `GET /health`. It answers at once and works in the background, and the leases keep it to one worker per claim or run. On startup it picks up any signed-off claims.
- `backend/agent_link.py` and the routes above. `backend/routes/runs.py` stops importing the agent.
- `npm run dev` starts all three on Windows, as `uv run` commands. The service runs without `--reload`, so a code change can't stop a claim.
- `uv run -m agent` and `POST /api/runs/open`.
- The dashboard: after a sign-off the claim shows as in progress and polls until paid. The payment shows the handler and the time. The live view handles a claim going back to in progress. "Run the queue" follows the table under "Only one worker at a time". Nothing else changes.
- The end-to-end tests: a stand-in for the service on port 8003 (`e2e/agent-standin.mjs`), which records what it receives.

Success criteria:

- [ ] Tests check the service: resume, run, one worker per claim, and signed-off claims picked up at startup.
- [ ] A test shows a sign-off stands when the service can't be reached, and that the call comes only after the save.
- [ ] Vitest checks the claim page after a sign-off (in progress, then paid with the handler and the time).
- [ ] Vitest checks the live view with a claim that returns to in progress.
- [ ] Vitest checks "Run the queue" in all three states of that table.
- [ ] An end-to-end test opens a run and sees "Run the queue" disabled with "A run is already in progress", then finishes the run and sees it enabled.
- [ ] An end-to-end test signs off on the dashboard and sees the claim in progress, with the stand-in on 8003 having received the resume call.
- [ ] The end-to-end tests have no way of reaching port 8002 (`UNDERCOVER_AGENT` is set to 8003 in `playwright.config.ts`).
- [ ] `npm run dev` starts all three on Windows, with `GET /health` answering on 8002.
- [ ] `npm run check` passes with `.env` moved out of the way.

### Phase 6: the live run, and the handover

Each live run starts with a reseed and is capped at five claims, on the default model. The lab's figures suggest about 3 cents each.

Success criteria:

- [ ] After reseeding Supabase, `uv run -m agent --cap 5` works five claims.
- [ ] A claim over the limit waits for a sign-off, with its graph paused.
- [ ] Signed off on the dashboard with the Playwright MCP server, it shows as paid within five seconds, with the handler and the time, checked with a screenshot.
- [ ] During a command-line run, checked with the Playwright MCP server, "Run the queue" is disabled with "A run is already in progress", and a second `uv run -m agent --cap 5` is refused.
- [ ] A second run, killed from the command line after a claim's first steps, carries on with the same thread the next time, with the attempts unchanged, one decision and no repeated steps.
- [ ] Within 20 seconds of that kill a new run is refused. After that, the dashboard offers to finish the stopped run.
- [ ] Through the Supabase MCP server, during the live run with all three processes up, `pg_stat_activity` shows no more than 12 connections whose user is postgres.
- [ ] Through Langfuse's API, the held claim's session has traces from before and after the sign-off.
- [ ] A signed-off claim with the service stopped stays in progress, and is paid when the service starts again.
- [ ] `docs/SPEC.md` (only its section on working the queue), `docs/TECH_STACK.md`, `docs/PROCESS.md` and `docs/STATUS.md` describe the product as it now is.
- [ ] `npm run check` passes with `.env` moved out of the way, and the results are reported.

Moving `.env` out of the way is a rename and back, and nothing reads it. Throughout, the keys stay in the environment of the processes that need them and are never printed.
