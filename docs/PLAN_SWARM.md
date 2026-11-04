# Plan: a swarm of claim agents and a scoreboard

The plan for `docs/SWARM.md`, on branch `week2day4-sarvjot`, made from `week2day3-sarvjot`.

SIDENOTE: For consistency with the course, please read `labs/week2day4.ipynb` and build the dispatcher in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

## What stays ours

- **The limit stays at $800.** The brief says $1,000, but our limit is `payout_approval_limit` in `data/company.json`. Nothing new hard-codes either figure, and the Rules in `docs/SPEC.md` stay as they are.
- **The live view stays**, and grows to follow a swarm: see "The live view" below.
- **The code stays in small modules.** `backend/api.py` stays the app, and the new modules are named below.
- **The labs stay untouched.** `labs/week2day3free.ipynb` and the Week 2 Day 4 notebooks stay out of every commit.

## How it will work

### The pieces

```
dashboard --POST /api/dispatches {n}--> backend --POST /dispatches {n}--> agent's service
                                                                             |
                                       backend <--POST /api/runs (creates the record)
                                                                             |
                                                    dispatcher graph (no model), max_concurrency = N
                                                      list_claims --Send per claim--> work_claim
                                                                                         |
                                                                  claim.work(claim_id, run_id)   <- the one door
                                                                                         |
                                                                  claim graph, its own thread, as today
```

### The dispatcher (`agent/dispatcher.py`, the agent's fifth part)

It's built like the lab's dispatcher: a `Dispatch` state, a `list_claims` node, a `fan_out` edge that returns one `Send("work_claim", ...)` per claim, and a `work_claim` node. There's no model, and no checkpointer.

- **`list_claims`** asks the backend for the run's claims, which the backend fixed when it created the run. For a dispatch, they are every claim in progress and every waiting claim, oldest submitted first. Evaluation copies are never among them. For an evaluation, they are its copies.
- **`work_claim`** calls `claim.work(claim_id, run_id)`. That's the only place the dispatcher touches the claim agent, so later it can point at the agent in the cloud. If the claim comes back `waiting`, meaning it failed once and went back to the queue, the same worker tries it once more. A second failure leaves it for a handler, as today.
- **`max_concurrency` = N** in the config, as in the lab. A test counts the claims inside `claim.work` at once and checks it never goes above N.
- **Retries:** `work_claim` has a `RetryPolicy` with `retry_on=(ModelRateLimitError, ModelTimeoutError)`. The waits grow, with jitter, so 25 agents don't all retry at the same moment. Its `error_handler` catches whatever is still failing when the retries run out. It records a step on the claim saying it will carry on next time, and leaves the claim in progress, so no error stops the dispatch.
- **When it ends**, the service tells the backend the run has finished. The backend builds the summary from the records.

### `claim.work(claim_id, run_id)`, the one door (`agent/claim.py`)

- **A claim in progress** is carried on from its last checkpoint on its own thread, as `carry_on` does today.
- **A waiting claim** is started on a new thread, as `run` does today.
- **A claim the service is already resuming after a sign-off** is skipped. Its lease is live, so `work` reports "another worker is on it" and moves on.
- **A rate limit or a timeout** isn't caught. It goes up to the dispatcher's `RetryPolicy` without failing the claim, so the retry carries on from the last saved step as the same attempt. That's safe because the backend never decides or pays a claim twice. The claim graph's own model retry stops retrying these two errors, so the dispatcher owns the waits rather than having two layers of retries multiply.
- **Any other error** fails the claim as it does today: back to the queue the first time, left for a handler the second time.
- **Each run of the graph** gets its own `PostgresSaver` on the process's shared pool, because one saver holds a lock around every read and write. The pool stays at 4 connections, and a claim agent waits for one rather than failing (the pool's timeout goes up to 120 seconds).
- **An evaluation copy held for sign-off** counts as finished. `work` then deletes the copy's thread from the checkpointer, so nothing is left waiting.
- **Time:** each call to the graph is timed and recorded with its run, and a call ends when the graph pauses at `sign_off`. So a wait for a handler is never counted. A resume after a sign-off is timed too, with no run.

### Cost and time (phase 1)

- **Cost:** the claim graph's model node reads OpenRouter's `usage` from each reply (`response_metadata["token_usage"]`: the prompt tokens, the completion tokens and `cost`, as in the lab). It records them with `POST /api/claims/{id}/usage`, which takes the run id or `null`, the model and a key. The key is the reply's message id, so a node that runs again after a crash records a second reply, which was real spend, but never records the same reply twice.
- **Time:** `POST /api/claims/{id}/work` records a working session (run id or `null`, started, finished). A run's time per claim adds up its sessions, and failed attempts are included.
- **Tables:** `usage` (claim, run, model, input and output tokens, cost, key) and `work_sessions` (claim, run, started, finished, seconds).

### GPT-6 Luna by default (phase 1)

`agent/model.py` defaults to `openai/gpt-6-luna` with `reasoning_effort="low"`. `MODEL_NAME` still chooses another model, which runs with no reasoning effort. `model.describe()` returns `{"model": ..., "reasoning": "low" | "none"}`, and the service records that on each run.

### Runs: dispatches and evaluations in one table

The `runs` table gets `kind` (`dispatch` or `evaluation`), `n`, `set_name` and `tiny` for an evaluation, `model` and `reasoning`. Its status is `running`, `finished` or `stopped`. The existing unique index on a running run keeps it to one dispatch or evaluation at a time, across both kinds. `cap`, `todos` and the run leases go:

- Only the service starts runs now.
- It refuses a second one itself with a 409.
- When it starts, it marks any run still `running` as `stopped`.

The claim leases stay, because a dispatch and a sign-off resume can still meet on one claim.

- `POST /api/dispatches {n}` (backend → service): a 202, a 409 from the service while a run is going, or a 503 with "The agent's service isn't running".
- `POST /api/evaluations {set_name, tiny, n}`: the same.
- `POST /api/runs {kind, n, set_name, tiny, model, reasoning}` (service → backend): creates the record, and for an evaluation creates its copies. Every field is required. A dispatch sends `set_name: null, tiny: false`, because the API rules allow no optional inputs.
- `POST /api/runs/{id}/finish` and `POST /api/runs/{id}/stop`.
- `GET /api/runs/current`, `GET /api/runs/{id}`: the run, each claim with where it stands, the model cost, the time, and, once it has ended, the summary.

`backend/agent_link.py` becomes `backend/agent_service.py`, the name the brief uses. It passes N and the set in the call to the service.

### The summary, from the records

Once a dispatch ends, `GET /api/runs/{id}` includes a summary built in `backend/runs.py`, with no model:

- how many claims were approved, declined and referred
- each payout waiting for a sign-off, with its amount
- each claim left for a handler, and each claim still in progress

The run panel shows it in place of the agent's summary.

### Evaluations and the answer key (phases 4 and 5)

- **Seeding:** two new tables hold the held-out claims (`held_out_claims`) and the handlers' decisions (`handler_decisions`: claim, set, decision, payout, `tiny`). The held-out claims never enter `claims`, and no claim operation reads either table. This build opens `data/evals/` for this, as the brief allows; `seed` loads only `decisions.json`, `held_out_claims.json` and `held_out_decisions.json`.
- **Copies:** creating an evaluation copies each claim of the set into `claims`, with a new id such as `EV7-CLM-1001`. The new id is written into the copy's record too. The copy has `evaluation_id` (its run) and `source_id` (the original). The queue, the live view, the dispatch's list and the service's startup all leave copies out.
- **No sign-off on a copy:** `POST /api/claims/{id}/sign-off` on a copy is refused with a 409, and the copy's page has no sign-off form. It says it's a copy for an evaluation instead.
- **Scoring**, in `backend/scoring.py`, from the evaluation's own records and the answer key:
  - `decision_accuracy`, `accuracy` (the decision matches and the payout is within a dollar), `cost_of_mistakes` (a wrongful decline costs $1,500, a wrongful approval its payout, a needless referral $50, a wrong amount on a right approval the difference), `straight_through`, model cost per claim, time per claim and the whole run's time
  - a claim the agent didn't decide counts as a referral with no payout
  - the functions mirror the lab's `is_right`, `mistake_cost` and `run_scores`
- **A stopped evaluation** shows as stopped, with the claims it got through and no measures.

### The dashboard

- **The queue page:**
  - "Run the queue" and "Claims in this run" give way to "Start a dispatch", with "Claim agents at once", from 1 to 25, starting at 3.
  - While a dispatch or evaluation is running, the button is disabled with "A dispatch or evaluation is already running".
  - If the service is down, the start says "The agent's service isn't running".
- **The run panel:**
  - each of the dispatch's claims, linked, with a badge for where it stands
  - the model cost and the time so far
  - the summary built from the records, once the dispatch ends
- **The Scoreboard page** (`#/scoreboard`), in the main navigation:
  - a form for an evaluation: set, the whole set or its five `tiny` claims, and N
  - the evaluations, newest first, each with its set, N, model, reasoning and every measure
  - each evaluation opens to `#/scoreboard/7`: every claim with the handler's decision and payout beside the agent's, the misses marked, and each claim linked to its page
- **The instructions page** shows only the claim agent's instructions.

### The live view

The live view follows one claim at a time today. With N at once it becomes a board:

- the dispatch's claims as cards, with the ones being worked at the front
- each card showing the agent's latest step while it works, and stamped with its outcome (Approved, Declined, Referred, Waiting for sign-off, Left for a handler) when it ends
- the run's numbers, its cost and its time across the top
- the summary from the records at the end

Esc still leaves, and an approval is still stamped only once it's paid. At N=1 it looks much as it does today. The live view shows dispatches, not evaluations.

### Langfuse

Each claim keeps its own session, named by its thread. `tracing.config` gains the run and adds `langfuse_tags: ["dispatch-12"]` or `["evaluation-13"]` to the metadata, so a whole run can be found with Langfuse's tag filter.

### What goes

- `agent/queue.py`, its middleware and `backend/instructions/queue.md`
- the to-do list: `write_todos`, its route and schema, the `todos` column and the to-do end-to-end test (ours is a column on `runs`, not a table, so the reseed drops it with the old `runs` table)
- `uv run -m agent --cap`, `POST /api/runs/open`, `take_claim`, the run leases and the "finish the stopped run" message

`uv run -m agent CLM-1001` still works one claim, with no run.

### Connections

| Process | Connections |
|---|---|
| Backend, port 8000 | At most 4 (SQLAlchemy pool) |
| Agent service, port 8002 | At most 4 (the checkpointer's pool, shared by every claim agent) |

That's 8 for us, plus Supabase's own, well within 12. 25 agents calling the backend at once share its 4 connections, so its `pool_timeout` goes up to 120 seconds and they wait rather than fail.

## Decisions for your review

1. **The live view becomes a board of the swarm** (above), in place of following one claim at a time. The other way is to keep following one claim, the oldest being worked. That stays closest to today's look, but at N=25 it would show only a fraction of the work.
2. **A failed claim is tried again straight away by the same worker**, not sent back to the end of the dispatch. It's simpler, and the brief only asks that the same dispatch tries it once more.
3. **The cap goes.** A dispatch works every claim in progress and waiting, as the brief asks. A trial run is now a small N on a reseeded queue, or an evaluation of the five `tiny` claims.
4. **The run leases go**, because only the service starts runs and it marks leftovers as stopped when it starts. The claim leases stay.
5. **`backend/agent_link.py` is renamed to `backend/agent_service.py`**, so it matches the brief and the briefs that come after it.
6. **Our `docs/CODE_STANDARDS.md` has no rules 10 and 13.** The brief's version lists the agent's parts there, and ours lists them in `docs/TECH_STACK.md`. So the dispatcher is added to `docs/TECH_STACK.md`, and `docs/CODE_STANDARDS.md` changes only if the build adds a standard.
7. **`npm run seed`** doesn't exist yet. It's added as `uv run -m backend.seed`, which already loads `.env` itself.

## Phases

Each phase ends with its criteria ticked here, `docs/STATUS.md` updated and a commit.

### Phase 1: GPT-6 Luna, and the cost and time of every claim

- `agent/model.py`: the new default and `describe()`.
- The `usage` and `work_sessions` tables, `POST /api/claims/{id}/usage` and `POST /api/claims/{id}/work`.
- The claim graph's model node records each reply's usage. `claim.work`'s forerunners, `run` and `carry_on`, time each call to the graph and take a run id, which is `null` for now.
- `tracing.config` takes the run and adds its tag.

Success criteria:

- [x] A test shows the default model is `openai/gpt-6-luna` with low effort, and that `MODEL_NAME` gives that model with no effort, which `describe()` reports as `none`.
- [x] A test on a stub model, whose replies carry OpenRouter's usage, shows each reply's tokens and cost recorded once against the claim, and a reply recorded again after a crash in the node not counted twice.
- [x] A test shows a claim held for sign-off records the time up to the pause and the time after the resume, and no time for the wait in between. The clock is moved on in the test, with no waiting.
- [x] A test shows a claim's usage and time recorded with its run, and with no run when there is none.
- [x] A test shows the trace's metadata carries `langfuse_tags` with the run, and no tag without one.
- [x] Both operations have an `operation_id`, a one-line docstring and no optional inputs (checked in `/openapi.json`).
- [x] `npm run check:python` passes.

### Phase 2: the dispatcher in place of the queue agent

- `agent/dispatcher.py`: the graph, with `RetryPolicy` and `error_handler` on `work_claim`.
- `claim.work(claim_id, run_id)`: the one door, with a saver per graph run on the shared pool, and rate limits and timeouts let through.
- `runs` gains `kind`, `n`, `set_name`, `tiny`, `model` and `reasoning`. `POST /api/runs`, `/finish`, `/stop` and the summary from the records.
- The queue agent, its instructions, the to-do list, `--cap` and the run leases go.

Success criteria, all on a stub model:

- [ ] A test with 10 claims and N=3 shows never more than 3 inside `claim.work` at once, and all 10 worked.
- [ ] A test lists a dispatch's claims: those in progress first and waiting, oldest submitted first, with no evaluation copies.
- [ ] A test gives one claim a `ModelRateLimitError` partway, and it carries on as the same attempt on the same thread, with one decision and no repeated steps.
- [ ] A test gives one claim rate limits until the retries run out. It stays in progress with its thread, the other claims finish, and the next dispatch carries it on.
- [ ] A test fails a claim with another error once. It goes back to the queue and is worked again in the same dispatch, and a claim failing twice is left for a handler.
- [ ] A test shows a claim being resumed after a sign-off, with a live lease, skipped by the dispatch.
- [ ] A test shows the summary built from the records: the counts, each payout waiting for a sign-off, and the claims left for a handler or in progress.
- [ ] A test shows a second run refused with a 409 while one is running, for either kind.
- [ ] A test shows each graph run gets its own saver, all on one pool.
- [ ] `uv run -m agent CLM-1001` still works one claim (a test of `__main__` on a stub).
- [ ] `agent/queue.py`, `backend/instructions/queue.md` and `write_todos` are gone, and `grep -r todos backend agent` finds nothing.
- [ ] `npm run check:python` passes, with coverage at 80% or more.

### Phase 3: starting a dispatch from the dashboard

- The service: `POST /dispatches {n}` answers at once or refuses with a 409, creates the run through the backend and works it in the background. At startup it marks runs still `running` as `stopped`.
- `backend/agent_service.py` and `POST /api/dispatches {n}`, with a 503 when the service is away.
- The queue page, the run panel and the live view board, as above. The instructions page shows the claim agent only.
- `npm run seed`. The stand-in on port 8003 records the body it receives.

Success criteria:

- [ ] Tests check the service: a start answers at once, a second start is refused with a 409, and runs left `running` are marked stopped at startup.
- [ ] A test shows `POST /api/dispatches` passes N to the service, and answers 503 with "The agent's service isn't running" when it can't be reached.
- [ ] Vitest checks N defaults to 3 and is held between 1 and 25, and that the button is disabled while a run is running.
- [ ] Vitest checks the run panel: the claims with their badges, the cost and the time, and the summary once it ends.
- [ ] Vitest checks the live view board: several claims worked at once, each stamped as it ends, and the summary at the end.
- [ ] An end-to-end test starts a dispatch at N=5 on the dashboard, and the stand-in receives `{"n": 5}`.
- [ ] The end-to-end test that played a capped run out through the API now plays out a dispatch, and the panel shows the summary from the records. The to-do list's test is gone.
- [ ] `npm run dev` starts all three on Windows, and `npm run seed` reseeds.
- [ ] `npm run check` passes with `.env` moved out of the way.

### Phase 4: evaluations

- Seeding the answer key into `held_out_claims` and `handler_decisions`.
- `POST /api/runs` for an evaluation makes its copies. The service's `POST /evaluations {set_name, tiny, n}` and the backend's `POST /api/evaluations`.
- Copies are left out of the queue, the dispatch, the live view and the service's startup, and are refused a sign-off.
- `backend/scoring.py` and `GET /api/evaluations` and `GET /api/evaluations/{id}`.

Success criteria, all on a stub model:

- [ ] A test runs an evaluation of the five `tiny` claims, and the queue's claims and their states are the same before and after.
- [ ] A test shows a copy held for sign-off counted as finished, with its thread gone from the checkpointer.
- [ ] A test shows a sign-off on a copy refused with a 409.
- [ ] A test shows `get_claim` on a copy holds its new id and nothing from the handlers' decisions: none of their fields, reasons or payouts.
- [ ] A test with a handful of claims, with the measures worked out by hand in the test, matches `scoring.py` on each one, including a claim the agent didn't decide counting as a referral.
- [ ] A test shows an evaluation records its set, N, model and reasoning, and each claim's decision, payout, reason, cost and time.
- [ ] A test shows an evaluation that stopped partway reported as stopped.
- [ ] A test shows a dispatch never takes a copy, and the service's startup never picks one up.
- [ ] Every new operation has an `operation_id`, a one-line docstring and no optional inputs.
- [ ] `npm run check:python` passes, with coverage at 80% or more.

### Phase 5: the scoreboard

- The Scoreboard page, the evaluation's page and the copy's claim page without a sign-off form.

Success criteria:

- [ ] Vitest checks the scoreboard: newest first, with every measure, and a stopped evaluation shown as stopped.
- [ ] Vitest checks an evaluation's page: the handler's decision and payout beside the agent's, the misses marked, and each claim linked.
- [ ] Vitest checks a copy's claim page shows no sign-off form.
- [ ] An end-to-end test starts an evaluation on the Scoreboard page, and the stand-in receives the set, `tiny` and N.
- [ ] An end-to-end test plays an evaluation out through the API, as `e2e/runs.spec.ts` does with a run, and sees it on the scoreboard with its measures.
- [ ] `npm run check` passes with `.env` moved out of the way.

### Phase 6: the live runs, and the handover

Reseed once, then only these runs, on the default model. By the labs' figures each costs a few cents.

Success criteria:

- [ ] With `npm run dev` running, a dispatch at N=3 started on the dashboard through the Playwright MCP server is stopped partway by killing every process listening on port 8002. On Windows that's `Get-NetTCPConnection -LocalPort 8002 -State Listen` and `Stop-Process -Force` on each owner. `npm run dev` then stops the others, and is started again.
- [ ] The stopped dispatch shows as stopped. A dispatch at N=25 carries on the claims left in progress as the same attempts (the same threads and attempts) and works the rest with 25 at once, which the claims' start times show.
- [ ] Its run takes well under the sum of its claims' times. Comparing claims worked from the start, each takes about as long as the claims at N=3. If they are slower, the report says where the time goes, keeping to 4 connections.
- [ ] Claims held for sign-off wait. A sign-off on the dashboard still pays within five seconds, checked with a screenshot.
- [ ] No claim fails for want of a database connection. During the dispatch, `pg_stat_activity` through the Supabase MCP server shows no more than 12 connections whose user is postgres.
- [ ] The run panel shows the dispatch's model cost and time, and the summary from the records. The live view board is checked with a screenshot.
- [ ] An evaluation of the evaluation set at N=25, and one of the held-out set's five `tiny` claims at N=5, appear on the scoreboard with every measure. The queue page's counts are the same before and after them.
- [ ] Through Langfuse's API, the claims of the N=25 dispatch are found together by its tag.
- [ ] `docs/SPEC.md` (its sections on working the queue and on what the team needs to see, with its Rules left alone), `docs/TECH_STACK.md`, `docs/PROCESS.md` (these runs replace the five-claim cap), `docs/CODE_STANDARDS.md` (see decision 6) and `docs/STATUS.md` describe the product as it now is.
- [ ] `npm run check` passes with `.env` moved out of the way, and the results are reported.

Moving `.env` out of the way is a rename and back, and nothing reads it. Throughout, the keys stay in the environment of the processes that need them and are never printed.
