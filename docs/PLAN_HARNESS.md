# Plan: the harness

The brief in `docs/HARNESS.md`: the UnderCover Agent organizes its own work. One run works the whole queue (or up to a cap), keeps a to-do list the team can watch, hands each claim to a fresh subagent, looks up the sections of the claims manual and the wording it needs, and recovers from failures without leaving a claim stuck.

This builds on the pilot (`docs/PLAN.md`, finished) and keeps what made it ours: the gold brand, the $800 sign-off limit and the live view.

## Approach

- **First, a codebase we can keep growing.** The pilot's backend is one 380-line `backend/main.py`, and the agent is one file. Before adding features, phase 1 splits them into modules with one job each: `backend/api.py` builds the app, the routes live in `backend/routes/`, the rules (states, the limit, attempts) in `backend/rules.py`, and the agent into a client, its tools, its middleware, the claim agent and the queue agent. Phase 1 changes no behavior, so the pilot's tests prove the split.
- **Our own harness, from LangChain's parts.** No Deep Agents or other framework, as the brief asks. Both agents use `create_agent`, which we already have. The to-do list, the subagent and the document lookup are our own tools that call the backend, so the backend holds the state the dashboard shows. Recovery uses LangChain's middleware: `ModelRetryMiddleware` for provider errors, `ModelCallLimitMiddleware` (30 calls a claim), and our own middleware that posts each step to the claim.
- **Two agents.**
  - The **queue agent** plans the run as a to-do list, lists the waiting claims, works them in the order it chooses through `work_claim`, and finishes with a summary for the handlers.
  - `work_claim` starts the **claim agent**, a subagent with a fresh thread and only its claim in view. It reports back one line: the decision and payout, or what went wrong. The queue agent never sees the subagent's steps, so its context stays small as the run goes on.
- **The backend owns the rules, as in the pilot.**
  - The cap, the attempts, "fails twice goes to a handler", "never decided or paid twice" and "can't finish while a claim within the cap is still waiting" are all checked in the backend.
  - The agent gets a refusal it can read, and the rule holds whatever the model does.
- **Runs are records, not memory.** The pilot kept its queue run in a Python dict, which a restart lost. A run is now a row: its cap, how many claims it will work, the claims in the order it took them, the to-do list, its state and its summary. The dashboard and the live view read it from there.
- **Documents by section.** The backend splits the policy wording and the claims manual on their `##` headings. The claim agent gets three tools:
  - `list_sections`: the contents of either document
  - `read_section`: one section in full
  - `search_documents`: a keyword search, for questions like "giraffe" or "receipts"

  `get_policy_wording`, which handed over the whole wording, goes. Each section read is recorded as a step of a new kind, `read`, and the claim page lists them under "What the agent read".
- **The limit comes from our settings.** `data/company.json` has the payout approval limit. I'll set it to $800 there, to match `docs/SPEC.md`, and the backend reads it from that file instead of a constant. The manual's section 3 still says $1,000. The backend enforces the limit, so the agent's reading can't change it. The brief says "$1,000" in "What stays the same"; we keep the spec's $800, which is the intent: the spec's rules stay as they are.
- **Tests never call a model.** As in the pilot, the stub chat model plays a script: one script for the queue agent and one per claim for the subagents.

### Claim states

| State | Shown as | When |
|---|---|---|
| `waiting` | Waiting | Seeded; or a failed attempt, the first time |
| `in_progress` | In progress | The claim agent is on it |
| `awaiting_sign_off` | Waiting for sign-off | Approved with a payout over $800 |
| `decided` | Decided | Declined, referred, or approved and paid |
| `needs_handler` | Left for a handler | **New.** Its second failed attempt |

A claim's `attempts` count goes up each time an attempt fails. When the backend starts, any claim left `in_progress` by a crash goes back to `waiting` as a failed attempt, so nothing stays stuck.

### Run states and the to-do list

- **A run** is `running`, `finished` (with the agent's summary) or `failed` (the queue agent itself broke). When it ends either way, any claim of the run still in progress is failed, so it goes back to the queue.
- **A to-do item** has the claim id, a short note and a state: `to_do`, `in_progress`, `done` or `left_for_handler`. The agent writes the whole list each time it changes it, like LangChain's `write_todos`, and the backend stores it on the run.

### The live view

- It keeps following the claim in progress, as in the pilot.
- "Claim 4 of 5" now comes from the run record: the position of the claim in the order the agent took it, out of the number the run will work, which is the cap or the number waiting, whichever is lower.
- A claim that fails and goes back to the queue leaves the screen without a stamp.
- A claim left for a handler gets a fifth stamp, **Left for a handler**, in Champagne Gold. That's the one brand color the stamps don't use yet.
- The summary screen adds the agent's own summary.

### Structure after phase 1

```
backend/
  api.py            the FastAPI app: lifespan, routers (uvicorn backend.api:app)
  db.py             schema, connection, seed and reseed
  seed.py           uv run -m backend.seed: start again from data/
  rules.py          claim states, the approval limit from company.json, moves
  schemas.py        the request bodies
  routes/claims.py  the queue, a claim, its steps, decisions, payment, sign-off
  routes/runs.py    queue runs (phase 1: the pilot's queue run, moved as is)
  routes/library.py the wording, the instructions, the handlers
agent/
  client.py         the backend client and readable refusals
  model.py          the model from MODEL_NAME or the default
  tools.py          the claim agent's tools
  claim.py          the claim agent: run(claim_id, thread_id)
  __main__.py       uv run -m agent CLM-1001
```

Phases 2 to 4 add `routes/documents.py`, `agent/middleware.py` and `agent/queue.py`, and the instructions move to `backend/instructions/claim.md` and `backend/instructions/queue.md`.

## Phase 1: the codebase split, and the limit from our settings

No new behavior. The same API at the same paths.

- Split `backend/main.py` and `agent/main.py` as above. `package.json`'s `dev:backend` and the Playwright config start `backend.api:app`.
- `backend/rules.py` reads `payout_approval_limit` from `data/company.json`, which I'll change to `800.00`.
- `uv run -m backend.seed` drops the tables and seeds them again from `data/`. Today the only way to reseed is to delete `undercover.db`.
- The tests move to match: `backend/tests/` by route module, and `agent/tests/`.

Success criteria:

- [x] `npm run check` passes in full with the pilot's tests, moved but otherwise unchanged in what they check, and Python coverage of at least 80%.
- [x] `backend/main.py` and `agent/main.py` are gone, and no module in `backend/` or `agent/` is over 200 lines.
- [x] A test shows the limit comes from `data/company.json`: approvals of $800.00 and $800.01 land on either side of it, as before.
- [x] `uv run -m backend.seed` on a database with decisions leaves 25 waiting claims and no decisions, payments or steps (checked through `GET /api/claims`).
- [x] `npm run dev` starts, and http://localhost:5173 shows the queue (screenshot).

## Phase 2: the manual and the wording, by section

- `GET /api/documents/{document}/sections`: the numbered section titles of `policy_wording` or `claims_manual`.
- `GET /api/documents/{document}/sections/{number}`: one section's text.
- `GET /api/documents/search/{query}`: the sections of both documents whose text contains every word of the query, with the matching lines.
- The claim agent's tools become:
  - `get_claim`
  - `list_sections`
  - `read_section`
  - `search_documents`
  - `record_decision`
  - `pay_claim`

  `get_policy_wording` is removed from the agent. The wording's route stays for the dashboard.
- Our middleware records each step on the claim, as `work()` does today. A `read_section` call is recorded as a `read` step, such as "Claims manual · 7. Interpretation notes".
- `backend/instructions/claim.md` is rewritten from the wording and the manual (never from `data/evals/`). It covers the manual's order of work, the three decisions and when to refer, the documents each benefit needs, repeat claims and meals without receipts, and looking up sections instead of guessing.
- The default model becomes `deepseek/deepseek-v4.1-flash` with low reasoning effort. `MODEL_NAME` still overrides it.
- `docs/SPEC.md`: the claims manual moves out of "Not for now", and the pilot section says decisions follow the wording and the manual.

Success criteria:

- [x] `uv run pytest -q` passes, with tests for each documents route: the wording's 12 sections and the manual's 14, section 7 of the manual containing "Wild animals", a search for "giraffe" finding it, and 404s for an unknown document or section.
- [x] A stub-model test: the claim agent lists the manual's sections, reads section 7 and records a decision. The claim's steps include a `read` step naming the manual and section 7, in order.
- [x] A test shows that no tool returns a whole document, and that nothing the agent can reach mentions `data/evals/` or its fields.
- [x] A test shows the default model is DeepSeek V4.1 Flash with low effort, and that `MODEL_NAME` overrides it.
- [x] `npm run check:python` passes with coverage of at least 80%.

## Phase 3: failures put right, claim by claim

- `claims.attempts`. `fail_claim` adds one: at 1 the claim goes back to `waiting`, at 2 to `needs_handler`, each with an `error` step saying why.
- On startup the backend fails any claim left `in_progress`, with the reason "The agent stopped partway".
- The claim agent's middleware:
  - `ModelRetryMiddleware`: 3 tries with backoff on provider errors and timeouts
  - `ModelCallLimitMiddleware`: 30 calls a claim
  - a request timeout on the model
  - backend refusals returned to the model as text (as `reply()` does now), never raised
- Whatever goes wrong, the claim agent's run fails the claim and returns a one-line report instead of raising. That covers the model, a tool error, the call limit, or finishing without a decision. One bad claim can't stop a run.
- **Never twice.**
  - A second decision on a claim that isn't in progress is refused (409), as now.
  - A second payment is refused (409), as now.
  - A claim that's `needs_handler` can't be started.

Success criteria:

- [x] `uv run pytest -q` passes, with stub-model tests for:
  - a model that raises: the claim goes back to `waiting` with `attempts` 1 and an `error` step
  - a second failure: the claim is `needs_handler` with `attempts` 2
  - a stub that never records a decision: failed with "finished without recording a decision"
  - a model that fails once and then answers: decided, with no failed attempt
  - more than 30 model calls: stopped, and the claim failed
- [x] A test shows a claim left `in_progress` is back to `waiting`, with one attempt, after the backend starts again.
- [x] Tests show a second `record_decision` and a second `pay_claim` on the same claim are refused, and the claim has one decision and at most one payment.
- [x] `npm run check:python` passes with coverage of at least 80%.

## Phase 4: one run works the queue

- **The run routes:**
  - `POST /api/runs` with `{"cap": 5}` starts a queue run in a background task (409 if one is running).
  - `GET /api/runs/current` returns the latest run: its state, cap, total, claims in order, to-do list and summary.
  - `PUT /api/runs/{run_id}/todos` stores the to-do list.
  - `POST /api/runs/{run_id}/claims/{claim_id}` adds a claim to the run and starts it. It's refused once the run has taken `cap` claims, unless the claim is a retry of one it already took.
  - `POST /api/runs/{run_id}/finish` with the summary. It's refused while a waiting claim remains and the cap isn't reached, and the refusal names the waiting claims.
  - `POST /api/runs/{run_id}/fail`.
- **The queue agent** (`agent/queue.py`, `backend/instructions/queue.md`) has these tools:
  - `list_waiting_claims`: id, type, amount and submitted date
  - `write_todos`
  - `work_claim(claim_id)`: adds the claim to the run, then runs the claim agent on a new thread, and returns its one line
  - `finish_run(summary)`

  It uses the same retry middleware, and a call limit sized to its cap.
- If the queue agent raises or stops without finishing, the run is failed, and its claims still in progress go back to the queue.
- `POST /api/claims/{id}/run` still runs the claim agent alone on one claim.
- The CLI:
  - `uv run -m agent --cap 5` starts a run through the backend and prints the summary when it's done.
  - `uv run -m agent CLM-1001` works one claim.
- `GET /api/instructions` returns both sets of instructions: `{"queue": ..., "claim": ...}`.
- The pilot's `POST /api/queue/run` and `GET /api/queue/run` go, replaced by the run routes. (They stay until phase 5 moves the dashboard to the run routes, so every commit stays green.)

Success criteria:

- [x] `uv run pytest -q` passes, with stub-model tests for:
  - a run with a cap of 2 on 25 waiting claims: the agent writes a to-do list, works 2 claims in the order it chose (not the submitted order), finishes with a summary; 23 claims stay waiting
  - the to-do list stored and returned by `GET /api/runs/current` with each item's state as the agent left it
  - a claim whose subagent fails: the run carries on to the next claim, then retries it, and it's decided on the second attempt
  - a claim that fails twice: `needs_handler`, its to-do item `left_for_handler`, and the run still finishes
  - the missed-claim check: `finish_run` is refused while a claim within the cap is waiting, the agent works it, and then finishes
  - the cap: a third `work_claim` with a cap of 2 is refused and leaves the claim waiting
  - a queue agent that raises: the run is `failed` and no claim is left in progress
- [x] A test shows each claim's steps are recorded on that claim, and none of them on any other claim.
- [x] `POST /api/runs` returns 409 while a run is going.
- [x] `npm run check:python` passes with coverage of at least 80%.

## Phase 5: the dashboard

- **The queue page:**
  - "Run the queue" with a "Claims in this run" number. It defaults to all the waiting claims; 5 is a trial.
  - A run panel: the to-do list for the current run, each item with its state, ticked off as the agent goes. When the run ends, the agent's summary appears.
  - The "Left for a handler" tile and badge.
- **The claim page:**
  - "What the agent read": the sections it opened, in order.
  - The number of attempts when it's more than one.
  - The `read` and `error` steps styled apart from tool calls.
- **The instructions page:** "Working the queue" and "Working a claim".
- **The live view:**
  - The numbers come from the run record.
  - The fifth stamp.
  - The agent's summary on the summary screen.
  - A claim sent back to the queue leaves without a stamp.

Success criteria:

- [x] `npm run check:ts` passes with coverage of at least 80%, with vitest tests for:
  - the to-do list and its states
  - the cap input and the request it sends
  - the summary
  - "What the agent read"
  - the new badge
  - the two sets of instructions
  - in the live view, using fake timers: "Claim 2 of 5" from the run record, the Left for a handler stamp, a failed claim leaving without a stamp, and the agent's summary
- [x] In the browser, with a run recorded through the API, the queue page shows the to-do list ticking off and then the summary. Light and dark screenshots.
- [x] In the browser, a claim page shows "What the agent read" with the sections in order.
- [x] The new colors and states match `docs/BRAND.md`: no outlines, no one-edge borders, no gradients.

## Phase 6: end-to-end, the live run and the handover

- Playwright tests, with the run, the to-do list and the decisions recorded through the API in place of a model:
  - the run panel ticking off
  - a claim left for a handler
  - a claim page's sections read
  - the live view following a capped run to its summary
- **The live run, as the brief asks.** I'll copy `undercover.db` to `undercover-pilot.db`, so your pilot's decisions are kept, then reseed. Then a run capped at 5 claims on DeepSeek V4.1 Flash: about 3 cents, from the Week 1 Day 5 lab's figures.
- `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` describe the product as it now is.

Success criteria:

- [ ] `npm run e2e` passes, with the tests above and the pilot's, updated for the run routes.
- [ ] After `uv run -m backend.seed`, `uv run -m agent --cap 5` works 5 claims on its own. Each is decided, waiting for sign-off or left for a handler, the other 20 stay waiting, and the run ends with a summary. The cost and time go in `docs/STATUS.md`.
- [ ] During that run, screenshots of the dashboard show the to-do list filling in and being ticked off, and each claim's steps with the sections it read.
- [ ] The live view plays the run through and ends on the summary with the agent's own summary.
- [ ] `npm run check` passes in full: ruff, pyright, pytest, ESLint, Prettier, tsc, vitest and Playwright.
- [ ] Every checkbox in this plan is ticked, and each phase has its own commit, made with the pre-commit hook.

## Notes

- The Playwright MCP server still fails to connect (`CONNECT_TIMEOUT`), so the browser checks use Playwright scripts and screenshots, as in the pilot. If you fix the MCP server first, I'll use it.
- `labs/week2day3free.ipynb` has your own changes. They stay out of every commit in this build.
