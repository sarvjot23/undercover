# Plan: the claims pilot

The pilot from `docs/SPEC.md`: a backend that holds the queue and enforces the rules, the UnderCover Agent that decides claims through the backend's API, and a dashboard where the handlers watch the queue, read each claim and decision, follow the agent step by step and sign off large payouts.

## Approach

- **The backend owns the rules.** The sign-off limit is checked in the backend, not in the agent's prompt, so the payment is blocked even if the agent tries to pay. Paying is its own operation that takes the amount, as `docs/TECH_STACK.md` asks.
- **SQLite through Python's `sqlite3`.** It needs no new dependency. The database file `undercover.db` (already ignored by `*.db`) is created and seeded from `data/` on first start. The path comes from `UNDERCOVER_DB`, so tests and the end-to-end run each get a fresh database.
- **`data/evals/` is never read.** The seed loads only the named files in `data/`, and a test checks that nothing the backend serves contains the eval decisions' file names or fields.
- **The agent sees only what a handler needs.** Its tools call the backend over HTTP: the claim, the policy with its plan's limits, the customer's name and claim history (no address, phone or date of birth), and the policy wording. Its instructions also come from the backend, so the dashboard shows exactly what the agent reads.
- **The agent reports each step.** `run(claim_id, thread_id)` streams the agent's updates and posts each one (a tool call, a tool's result, the final answer) to the backend. The dashboard polls the claim while the agent is working.
- **The dashboard starts the agent.** "Run the agent" on a claim calls `POST /api/claims/{id}/run`, and "Run the queue" calls `POST /api/queue/run`, which works through every waiting claim in turn, one at a time. Both run in a background task. Tests never call a model: pytest uses a stub model, and the end-to-end tests record decisions through the same API operations the agent uses.
- **The live view follows the claims, not the agent.** The full-screen view watches for the claim that's in progress and shows its outcome when it leaves that state. It works the same for a queue run, a single run or decisions recorded through the API, so the end-to-end tests can drive it without a model. The animations are CSS keyframes, with no new library, and they reduce to plain fades under `prefers-reduced-motion`.
- **No new libraries** beyond what's installed. The dashboard has three views (the queue, a claim and the instructions), so a small hash router does the job without React Router.

### Claim states

| State | Shown as | When |
|---|---|---|
| `waiting` | Waiting | Seeded; or the agent's run failed |
| `in_progress` | In progress | The agent is working on it |
| `awaiting_sign_off` | Waiting for sign-off | Approved with a payout over $800 |
| `decided` | Decided | Declined, referred, or approved and paid |

### The sign-off limit: please confirm

`docs/SPEC.md` says $800, but `data/company.json` still says `payout_approval_limit: 1000.00`, and `data/README.md` and the eval tags (`over_approval_limit`) are at $1,000. I'll follow the spec: the backend has one constant, `APPROVAL_LIMIT = 800`, with no change to `data/`. If the spec should be $1,000 after all, it's a one-line change.

## Phase 1: the records in the backend

The database, the seed and the read-only API.

- `backend/db.py`: the schema (claims, policies, customers, plans, handlers, decisions, payments, steps), the seed from `data/`, and a connection per request.
- Routes: `list_claims`, `get_claim` (with its policy, plan, customer, decision and payment; the steps have their own route, `list_steps`, so the agent never reads its own earlier steps back), `get_policy_wording`, `get_instructions` and `list_handlers`.
- The agent's instructions in `backend/instructions.md`, served read only.

Success criteria:

- [x] `uv run pytest -q` passes, with tests for each route and the seed.
- [x] A fresh start seeds 25 claims, all `waiting`: `GET /api/claims` returns 25 rows.
- [x] `GET /api/claims/CLM-1001` returns the claim with policy `POL-2001` on the Premium plan, its limits and Maya Patel's earlier claim CLM-0412.
- [x] `GET /api/claims/CLM-9999` returns 404.
- [x] `GET /api/policy-wording` returns the wording, starting with "# UnderCover Travel Insurance: Policy Wording".
- [x] A test shows that no file under `data/evals/` is opened while seeding, and that no response contains eval fields such as `difficulty` or `failure_class`.
- [x] Every route has an `operation_id`, a one-line docstring and no optional inputs: a test walks `app.openapi()` to check.
- [x] `npm run check:python` passes with coverage of at least 80%.

## Phase 2: decisions, payment and sign-off

The rules, enforced in the backend.

- `start_claim`: `waiting` to `in_progress`; 409 from any other state.
- `record_decision`: decision (`approve`, `decline` or `refer`), payout, reasons in two or three sentences, and the policy section. A decline or a referral has a payout of $0. An approval over $800 moves to `awaiting_sign_off`, and anything else to `decided`.
- `pay_claim` takes the amount. It's refused (409) while the claim is waiting for sign-off, if the amount isn't the approved payout, or if it's already paid. Otherwise it records the payment (no real money moves).
- `sign_off` takes a handler id: it records the handler, releases the payment and moves the claim to `decided`.
- `add_step` records one step of the agent's work. `fail_claim` sends a claim back to `waiting` after a failed run.

Success criteria:

- [x] `uv run pytest -q` passes, with a test for each transition and each refusal.
- [x] An approval of $650 goes to `decided`, and `pay_claim` with $650 records a payment.
- [x] An approval of $800.00 is `decided`, and $800.01 is `awaiting_sign_off`.
- [x] On an approval of $1,200 waiting for sign-off, `pay_claim` with $1,200 returns 409 and no payment is recorded. After `sign_off` by HND-01, the payment is recorded with the handler and the claim is `decided`.
- [x] `pay_claim` with a different amount from the approved payout returns 409.
- [x] A decline with a payout above $0 returns 422.
- [x] `npm run check:python` passes with coverage of at least 80%.

## Phase 3: the UnderCover Agent

The agent decides claims through the backend.

- Tools: `get_claim`, `get_policy_wording`, `record_decision` and `pay_claim`. Each one is a call to the backend. The system prompt is fetched from `GET /api/instructions`.
- `run(claim_id, thread_id)` starts the claim, streams the agent's updates, posts each step, and calls `fail_claim` if the run raises.
- `POST /api/claims/{id}/run` starts the agent in a background task with a new thread id.
- The model is `openai/gpt-6-luna` with low effort, or `MODEL_NAME` if set, as in the skeleton.
- `uv run -m agent CLM-1001` runs the agent on one claim from the command line, with the backend running.

Success criteria:

- [ ] `uv run pytest -q` passes. With a stub model, scripted runs: an approval under $800 that ends paid and `decided`; a decline; and an approval over $800 where the stub then calls `pay_claim` and is refused, leaving the claim `awaiting_sign_off` with no payment.
- [ ] A test shows that a run records its steps in order: tool calls, results and the final answer.
- [ ] A test shows that a run that raises sends the claim back to `waiting` with a step saying it failed.
- [ ] A test shows that the agent's tools call only `/api/` routes on the backend and that the prompt comes from `/api/instructions`.
- [ ] A live run on CLM-1001 with `gpt-6-luna` (about a tenth of a cent) ends with a decision, two or three sentences of reasons, a policy section and its steps in `GET /api/claims/CLM-1001`. This is the only check that calls a real model.
- [ ] `npm run check:python` passes with coverage of at least 80%.

## Phase 4: the dashboard's queue and instructions

The look from `docs/BRAND.md`, and the first two views.

- Fonts from Google Fonts in `index.html`: Instrument Sans, Instrument Serif and JetBrains Mono. Colors and surfaces as CSS variables, for light and dark mode by `prefers-color-scheme`.
- The queue: a table of all 25 claims with the id, customer, claim type, amount claimed, submitted date and a status badge. Claim ids, money and dates are in JetBrains Mono, and money looks like $1,250.00. The status colors are Gold, Champagne Gold, Antique Gold and Steel Gray, in the order of the table above.
- The agent's instructions, read only.
- A small hash router: `#/` for the queue, `#/claims/CLM-1001` for a claim, and `#/instructions`.

Success criteria:

- [ ] `npm run check:ts` passes, with vitest tests for the queue, the badges, money formatting and the router, and coverage of at least 80%.
- [ ] In the browser with the Playwright MCP server, the queue shows 25 rows, all "Waiting", in light and dark mode, and the colors and fonts match `docs/BRAND.md` (screenshots checked).
- [ ] The instructions view shows the text from `backend/instructions.md` and has no way to edit it.
- [ ] No panel has an outline or a one-edge border, and nothing uses a gradient.

## Phase 5: a claim in full, the agent at work and sign-off

- The claim view: the story, the items, the documents, the policy and plan, the customer's claim history, and the decision with its payout, reasons and policy section.
- "Run the agent" on a waiting claim. While the claim is in progress, the view polls every second and adds each step as it arrives.
- On a claim waiting for sign-off: a handler picker and "Sign off". The payout and reasons are shown above it.

Success criteria:

- [ ] `npm run check:ts` passes, with tests for the claim view, polling that stops once the claim leaves `in_progress`, and sign-off. Coverage is at least 80%.
- [ ] In the browser, CLM-1001 shows its story, its three items totaling $420.00, its four documents and Maya Patel's earlier claim.
- [ ] In the browser, with a live run on one claim, the steps appear one by one while it runs, and then the decision.
- [ ] In the browser, an approval over $800 (recorded through the API) shows "Waiting for sign-off" and no payment. After signing off as Dana Whitfield, it shows "Decided" and the payment, with her name.

## Phase 6: the live view

A full-screen view of the agent working through the queue, one claim after another.

- `POST /api/queue/run` runs the agent on each waiting claim in the order submitted. It returns 409 while a queue run is already going, and `GET /api/queue/run` says whether one is running and how far it has got.
- "Run the queue" on the queue view starts the run and opens the live view at `#/live`, full screen (the browser's Fullscreen API, filling the window if that's refused). Esc leaves it.
- The current claim fills the screen: the claim id, the customer, the claim type, the amount claimed, the summary, the items and the plan. Next to it, the agent's steps slide in as they arrive.
- When the decision lands, a stamp animates in over the claim (scale, fade and a slight turn, about 600 ms) with the outcome and its color: **Approved** in Gold, with the payout counting up to the amount; **Declined** in Steel Gray; **Referred** in Antique Gold; and **Waiting for sign-off** in Burnished Gold, for an approval over $800. The reasons and the policy section appear under it.
- After about 3 seconds, the card slides out and the next claim slides in. Across the top: "Claim 4 of 25", a progress bar, and a running count of each outcome.
- When the queue is done, a summary screen shows the counts of each outcome, the total paid and the total waiting for sign-off, with a link back to the queue.

Success criteria:

- [ ] `uv run pytest -q` passes, with stub-model tests that a queue run decides every waiting claim in order, skips claims that aren't waiting, and returns 409 while one is running. Coverage is at least 80%.
- [ ] `npm run check:ts` passes, with vitest tests using fake timers: the stamp for each of the four outcomes, the hold before the next claim, the progress and counts, the summary screen, and Esc leaving the view. Coverage is at least 80%.
- [ ] In the browser, with decisions recorded through the API, the live view shows each claim full screen, then its stamp, then moves on to the next, and ends on the summary screen (screenshots of a claim in progress, each stamp and the summary).
- [ ] In the browser, with reduced motion turned on, the stamps and the move to the next claim fade without scaling or sliding.
- [ ] A live queue run with `gpt-6-luna` on the 25 claims (about a cent) plays through in the live view and ends on the summary screen.

## Phase 7: end-to-end tests and handover

- Playwright tests against a fresh database (`UNDERCOVER_DB` set in `playwright.config.ts`), with decisions recorded through the API in place of a model.
- `docs/STATUS.md` rewritten: what's built, how to run it, and how to run the agent.

Success criteria:

- [ ] `npm run e2e` passes, with tests for: the queue shows 25 claims; a claim's detail page; an approval under $800 shows "Decided"; an approval over $800 shows "Waiting for sign-off", the payment is refused, and after sign-off it's "Decided" with the payment; the instructions page; and the live view following two claims through to their stamps.
- [ ] `npm run check` passes in full: ruff, pyright, pytest, ESLint, Prettier, tsc, vitest and Playwright.
- [ ] Following `docs/STATUS.md` from a fresh clone (`uv sync`, `npm install`, `npm run dev`) gives a working dashboard at http://localhost:5173.
- [ ] Every checkbox in this plan is ticked and each phase has its own commit, made with the pre-commit hook.
