# Plan: security changes before UnderCover goes on AWS

The plan for `docs/SECURE.md`, on branch `week3day2-sarvjot`, made from `week2day5-sarvjot`.

SIDENOTE: For consistency with the course, please read `labs/week3day2_lab1.ipynb` and build the check in step 2 in the same style as the lab, and read `labs/week3day2_lab2.ipynb`, which deploys the app, without running it. Where the lab and this document differ, follow this document. Include this sidenote in your plan too.

The brief's four steps are phases 1 to 4, one each, with a commit at the end of each. Phase 5 reseeds once, does every live check, brings the documents up to date and reports what the checks spent. Nothing in this plan touches AWS.

## What stays ours

- **The limit stays at $800.** The approval limit is a setting, seeded from `data/company.json`. The payment's new 403 reads the current setting. The Gateway's own Policy, at $1,000, comes with the deployment and sits above it.
- **The code stays in small modules.** The new ones are `backend/keys.py` (who is calling: the key or a handler), `agent/screening.py` (the check), `backend/agent_api.py` (the agent's OpenAPI document), `backend/static.py` (serving the dashboard's build) and `backend/main.py` (the app and its Lambda handler).
- **The labs stay out of every commit.**

## Where the brief's notes don't match our build

The notes describe Ed's improver build. Ours differs, so here is how each note maps onto our code.

| The note says | In our build |
|---|---|
| `backend/main.py` is the app, and the deployment runs `backend.main:app` with the handler `backend.main.handler` | Our app is built in `backend/api.py`. We add `backend/main.py`, which imports that app and adds `handler = Mangum(app, lifespan="off")` at the end, so the lab's deployment finds both names. `npm run dev` and the end-to-end backend move to `backend.main:app`, so what we test is what we deploy. |
| `agent/connection.py` holds the one `httpx.Client` | Ours is `backend()` in `agent/client.py`, which makes a fresh client for each call. Every part of the agent goes through it: the tools, the graph, the claim work, the dispatcher, the leases, the service and `agent/improver_client.py`. `backend()` reads `UNDERCOVER_API_KEY` each time it makes a client, which covers the command line loading `.env` late. The agent's tests swap `backend()` for a test client, and that swap sends the test key too. |
| The routes are in `main.py`, `runs.py`, `configuration.py` and `improvement.py`, with `SignedIn` in `backend/dependencies.py` | Ours are in `backend/routes/*.py`, with `SignedIn` and `Approver` in `backend/auth.py`. |
| The claim graph is in `agent/harness.py`, with `wait_for_sign_off` and `pay` | Ours is `agent/graph.py`. Its nodes are `agent`, `record`, `tools`, `sign_off`, `pay` and `close`. Its first message only names the claim, as in Ed's build, so the check fetches the claim itself. |
| `sign_off_claim`, `resume_claim` and `pay` | Ours are `sign_off` in `backend/routes/claims.py`, `resume_claim` and `pick_up_signed_off` in `agent/service.py`, and `pay` in `agent/graph.py`. |
| `pay_claim` checks the decision before the amount | Ours does the same, in `backend/routes/claims.py`. |
| `seed` is in `backend/database.py`, and the pool is set up in `engine_for` | Ours are `seed` and `postgres_engine`/`build_engine` in `backend/db.py`, with `MAX_CONNECTIONS = 4`. Ours already sets `prepare_threshold` to 0 for the session pooler, and on Lambda it becomes `None`. |
| The startup hook in `backend/main.py` | Ours is `lifespan` in `backend/api.py`. It runs `db.init()` and starts the `warm_up` thread. |
| `e2e/api.ts`, `finishOpenRound`, `agent.spec.ts` | Ours plays the agent in `e2e/api.ts` and checks sign-off in `e2e/claims.spec.ts` and `e2e/runs.spec.ts`. We have no `finishOpenRound` and no `agent.spec.ts`. |
| The `server` group needs adding | It's already in `pyproject.toml`, from the improver build. We check it against what the backend imports, which is fastapi, sqlalchemy, psycopg, pyjwt, httpx, openrouter and pydantic (through fastapi), plus mangum and uvicorn. `python-dotenv` is used only by `backend/seed.py`, which the app never imports. |

### Three choices to note before you approve

1. **The eight operations.** Our claim agent's tools are `get_claim` (which already returns the policy, the plan and the customer's previous claims), `list_sections`, `read_section`, `search_documents`, `calculate_payout` and `record_decision`; paying is a step of the graph. The brief's document needs `get_policy` and `get_claim_history`, which we don't have as routes. We add them as two small reads, `GET /api/policies/{policy_id}` (the policy with its plan's limits) and `GET /api/customers/{customer_id}/claims` (the customer's claim history). The claim agent's own tools don't change. `list_sections` is left out of the document, because the brief asks for exactly eight operations. On Day 3, when the agent moves onto the Gateway's tools, it will find sections only through `search_documents` and `read_section`.
2. **The check's step on the dashboard.** We add a step kind, `check`, which the dashboard labels "Security check". It's always the first step on a claim. We don't reuse `tool_result` for it, because the check isn't one of the agent's tools.
3. **The key never shows in the agent's document.** FastAPI would add an `X-API-Key` header parameter to every operation if we read the key with `Header()`. Our key check reads it from the `Request` instead, as does the shared check of key-or-handler, so the document has no key input and no security scheme.

---

## Phase 1: An API key for the agent

**What it builds.** `backend/keys.py` has three dependencies:

- `AgentKey` checks `X-API-Key` against `UNDERCOVER_API_KEY` with `secrets.compare_digest`, reading the setting on each request. When the setting is missing or empty, it refuses every request.
- `Reader` accepts either the key or a signed-in handler, and gives 401 when it has neither.
- `SignedIn` and `Approver` stay where they are in `backend/auth.py`. Neither one looks at the key, so the key never stands in for a handler.

Every route gets exactly one rule:

| Rule | Routes |
|---|---|
| Open | `GET /api/health` |
| The agent's side only (`AgentKey`) | Claims: start, steps (POST), calculate payout, decision, payment, fail, lease and release, usage, work. Runs: create, finish and stop. Rounds: `POST /api/rounds/records`; under `/api/rounds/{id}/`, the instructions, view, first-evaluations, spending, progress, proposals, decisions (the review it records for a handler), verdict, finish, halt and usage. |
| Shared reads (`Reader`) | The queue, a claim, its standing, its steps (GET), the documents (search, sections, a section), the current configuration and a version, a run, the running run, the open round, a round, and the settings. Phase 3 adds the policy, the claim history and the agent's document. |
| A handler (`SignedIn`, or `Approver` where it's needed today) | Everything else the dashboard calls: the handlers, the policy wording, the evaluations, the versions with their diffs, the recipes, the current run, the rounds list, and every action (sign-off, run the agent, start a dispatch, an evaluation or a round, stop a round, decide on a proposal, change the settings). |

**The agent side.**

- `agent/client.backend()` sends `X-API-Key` on every request.
- `agent/service.py` checks the key when it starts. Without it, startup stops with "UNDERCOVER_API_KEY is missing".
- `.env` gets `UNDERCOVER_API_KEY` from `secrets.token_urlsafe(32)` if it isn't there yet. We add it without printing it or opening the rest of `.env`.
- The tests set a fixed test key in `backend/tests/conftest.py` and `agent/tests/conftest.py`.
- `playwright.config.ts` gives the end-to-end backend a fixed key, and `e2e/api.ts` sends it.

- [x] `backend/tests/test_keys.py`:
  - an agent route (recording a decision) with no key, a wrong key and the right key gives 401, 401 and 200
  - a shared read (`GET /api/claims/CLM-1001`) with the key, with a handler's token and with neither gives 200, 200 and 401
  - a handler action (a sign-off and starting a dispatch) with only the key gives 401
  - with `UNDERCOVER_API_KEY` unset, the app still starts, a handler still reads the queue, and every agent route gives 401 even with a key sent
  - `/api/health` is open
- [x] A test walks every route in the app and checks each one has exactly one of the four rules, so a new route can't be left open by mistake.
- [x] A test checks `secrets.compare_digest` does the comparison.
- [x] An agent test checks that every request from `agent/client.backend()` carries the key, including from the improver's client. Another checks the service refuses to start without the key.
- [x] `npm run check` passes, with the end-to-end specs playing the agent with the key.
- [x] `docs/STATUS.md` is updated, and the phase is committed.

## Phase 2: A check for instructions hidden in a claim

**What it builds.** `agent/screening.py`, in the lab's style:

- the lab's `SCREEN_INSTRUCTIONS`
- the lab's `Screening` model, with `reason` first and then `instructions_found`
- `screen(claim)`, which calls the model with `with_structured_output(Screening, include_raw=True)` so that it gets each reply's usage

The check reads the claim's own fields as JSON, the way the agent's `get_claim` shows them. Those are the fields the customer wrote: the summary, the story, the items, the documents and the rest of the claim record, without the policy, the plan or the customer record.

- **The model.** `agent/model.py` gets `check_model()`: `openai/gpt-6-luna` at effort `none`, or `MODEL_NAME` with no effort. A single helper in `agent/model.py` reads `MODEL_NAME`, and both `model()` and `check_model()` use it.
- **The graph.** It gets a first node, `check`, between START and `agent`:
  - It fetches the claim and calls `screen`. If the answer can't be read, it tries again, for up to 3 attempts.
  - It records each attempt's usage with the claim's run, so the cost lands on the scoreboard.
  - It records a `check` step with the result.
  - When it flags the claim, it records a referral with a payout of 0, the check's reason, and the section "Security check: instructions found in the claim", then goes to `close`. The claim agent's model is never built.
  - When it finds nothing, it goes to `agent`.
  - If the check still can't be read after 3 attempts, or hits any error, a timeout or rate limit included, it raises an ordinary error. The claim then fails as any other error does today. It isn't passed up to the dispatcher to wait out.
- **When it runs.** Work that carries on from saved progress resumes after the check, so the check doesn't run again. A claim that starts again from its first message runs through the `check` node again.
- **Outside the improver's reach.** The check lives in code, not in `backend/instructions/` or the versioned configuration, so the improver can't see or change it.
- **The step on the dashboard.** The backend's `Step` kinds gain `check`, and `Steps.tsx` labels it "Security check".
- **CLM-1901.** `seed` in `backend/db.py` also reads `data/security/claims.json`, `policies.json` and `customers.json`, after `data/claims.json`, which doesn't change. `decisions.json` is not seeded.

- [x] `agent/tests/test_screening.py`, all on a stub model:
  - When a claim is flagged, it's referred with a payout of 0, the reason, and the security-check section. The claim agent's model is never called, and a `check` step comes first.
  - When a claim passes, the claim agent works it as before, and the `check` step comes first.
  - When an answer can't be read twice and then can, the claim goes on, with 3 calls recorded in its usage.
  - When an answer can't be read three times, the claim fails as any error does: back to the queue, or to a handler on the second failure.
  - When the check hits a timeout, the claim fails the same way and isn't left in progress.
  - A claim carried on from saved progress, or resumed after a sign-off, doesn't call the check again.
- [x] A test checks the check's model: Luna at `none`, or `MODEL_NAME` with no effort.
- [x] A backend test finds CLM-1901 waiting in the queue after seeding, and in neither evaluation set's claims. It also checks that the answer key's counts and `data/claims.json` haven't changed.
- [x] The dashboard tests show a `check` step labelled "Security check".
- [x] `npm run check` passes. `docs/STATUS.md` is updated, and the phase is committed.

## Phase 3: The agent's own API, and a sign-off that pays

**What it builds.**

- **Two new reads.** `get_policy` (`GET /api/policies/{policy_id}`) and `get_claim_history` (`GET /api/customers/{customer_id}/claims`), both shared reads. Each has an `operation_id`, a one-line docstring and no optional inputs.
- **The agent's document.** `backend/agent_api.py` builds it with FastAPI's `get_openapi` over exactly the eight routes: `get_claim`, `get_policy`, `get_claim_history`, `search_documents`, `read_section`, `calculate_payout`, `record_decision` and `pay_claim`.
  - It has no `servers` and no key input.
  - The payment's body keeps `amount`.
  - It's served at `GET /api/agent/openapi.json` as a shared read.
- **The payment limit.** `pay_claim` first refuses any `amount` over the current approval limit, with a 403 that names the limit, before it looks at the claim.
- **A sign-off pays.** `sign_off` records the sign-off and the payment together, with who and when, and the claim is `decided`. It then still nudges the agent's service to close the claim's thread. That's best-effort: if the service can't be reached, nothing changes.
- **The agent's side.**
  - In the graph, `sign_off` now leads to `close` rather than `pay`. A claim resumed after a sign-off finishes its work and records its answer without calling the payment.
  - `carry_on` and `pick_up_signed_off` resume a signed-off claim's paused thread even though the claim is already decided.
  - An approval within the limit is still paid by the `pay` node, as today.

- [ ] A test checks the document's operation ids are exactly the eight, that it has no `servers` and no `X-API-Key` parameter anywhere, that `pay_claim`'s body has `amount`, and that each operation's description is its docstring.
- [ ] A test checks the document gives 401 with neither a key nor a handler.
- [ ] A test checks that a payment of $5,000 on a claim that was never approved gets a 403 naming $800.
- [ ] A test checks that Dana's sign-off pays the claim once: the claim is decided, and a second sign-off or a payment call is refused, with one payment row.
- [ ] An agent test checks that a claim paused for sign-off, then signed off and resumed, makes no payment call and ends with a `close` answer.
- [ ] `get_policy` and `get_claim_history` return what `get_claim` already shows for CLM-1001.
- [ ] The end-to-end specs follow the new sign-off: after Dana signs off, the claim shows as paid with no step from the agent.
- [ ] `npm run check` passes. `docs/STATUS.md` is updated, and the phase is committed.

## Phase 4: Ready for Lambda

**What it builds.**

- **`npm run build`** runs `vite build dashboard` into `dashboard/dist`.
  - `vite.config.ts` sets `envDir` to the repo root in both `development` and `production` modes. Vite reads `.env` when it's there and the `VITE_` variables from the environment otherwise. The `test` and `e2e` modes still read no `.env`.
  - The build must print no warnings. If Vite warns about chunk size, we split the Supabase client into a chunk of its own rather than raise the limit.
  - `dashboard/dist/` and `build/` go in `.gitignore`.
- **`backend/static.py`** serves the built dashboard when `dashboard/dist` exists.
  - The files under `assets/` are served at their own paths.
  - Any other GET outside `/api/` returns `index.html`.
  - An unknown `/api/...` path still gets FastAPI's 404 in JSON.
  - The fallback route stays out of the OpenAPI document. Without the folder, nothing is added.
- **`backend/main.py`**: `from backend.api import app` and `handler = Mangum(app, lifespan="off")`.
  - The app answers every request without `lifespan` having run. The tables exist on Supabase already, and nothing else relies on the startup hook.
  - Nothing at run time imports `agent/`, reads outside the package or writes a file.
- **The database on Lambda.** When `AWS_LAMBDA_FUNCTION_NAME` is set, `build_engine` uses `NullPool` with `prepare_threshold=None`, and `warm_up` isn't started. Without it, the pool is as today.
- **The server group check.** `npm run check:server` runs `uv run --isolated --no-dev --only-group server python -c "import backend.main"`. It goes into `npm run check` after the Python checks. `pyproject.toml`'s `server` group is checked against the imports listed above.
- **The environment.** The backend runs with only `DATABASE_URL`, `VITE_SUPABASE_URL` and `UNDERCOVER_API_KEY`.
  - `UNDERCOVER_AGENT` and `JUDGE_URL` have defaults.
  - `MODEL_NAME` is optional.
  - `OPENROUTER_API_KEY` is needed only by the judge, at the end of an evaluation, which can't start on Lambda without the agent's service.
- **`docs/TECH_STACK.md`** gets a Deployment section: `npm run build` writes `dashboard/dist`; the package holds `backend/`, `data/`, `dashboard/dist/` and the `server` group; the Lambda handler is `backend.main.handler`; a web server runs `backend.main:app`; and the environment holds the three variables.

- [ ] A test calls `handler` with a Function URL event (version 2.0) for `/api/health` and gets 200 `{"status": "ok"}`.
- [ ] With a stand-in `dist` folder holding `index.html` and `assets/app.js`, a test gets `index.html` for `/` and `/scoreboard/4`, gets the JS file at its path, and gets a 404 in JSON for `/api/nope`.
- [ ] A test with `AWS_LAMBDA_FUNCTION_NAME` set, and a Postgres URL on port 6543, finds a `NullPool` engine with `prepare_threshold` set to `None`, using a fresh `build_engine` and no real connection. Without the setting, the pool of 4 is unchanged.
- [ ] `npm run build` passes with no warnings, and `npm run check:server` passes inside `npm run check`.
- [ ] A test checks that importing `backend.main` loads no module from `agent`.
- [ ] `npm run check` passes with `.env` moved out of the way. `docs/STATUS.md` is updated, and the phase is committed.

## Phase 5: The live checks and the handover

We reseed once with `npm run seed`, then run `npm run dev` on the default model. Each check is done once, in this order.

- [ ] The dashboard works as before for Dana, signed in through the Playwright MCP server with `HANDLER_PASSWORD` from the environment, never printed.
- [ ] `curl -X POST http://127.0.0.1:8000/api/claims/CLM-1001/decision` without the key gets 401.
- [ ] `uv run -m agent CLM-1001` works the claim to a decision.
- [ ] A dispatch with 3 agents at once works the rest of the queue as before. CLM-1901 is referred with the check's reason, and the claim page shows the "Security check" step first, with the reason.
- [ ] An evaluation of the evaluation set's tiny five flags none of them.
- [ ] Dana signs off a held payout on the dashboard, and it's paid once with no call from the agent.
- [ ] We stop `npm run dev`. The backend alone, started with `AWS_LAMBDA_FUNCTION_NAME` set and `DATABASE_URL` switched to port 6543 in that process only, serves the claims to a signed-in handler.
- [ ] After `npm run build`, `uv run -m uvicorn backend.main:app` serves the dashboard at `http://127.0.0.1:8000`, where Dana signs in and sees the claims, checked through the Playwright MCP server.
- [ ] We build the deployment package in a temporary folder, as Lab 2 does (`uv export --only-group server`, `uv pip install --python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary :all:`, then `backend/`, `data/` and `dashboard/dist/`), zip it, and report its size against Lambda's 50 MB limit. The folder is deleted afterwards.
- [ ] We report what the live checks spent, from the runs' recorded cost.
- [ ] The docs are updated:
  - `docs/SPEC.md` for the key, the check and the sign-off that pays
  - `docs/TECH_STACK.md` for the key, the check, the agent's document and the deployment
  - `docs/PROCESS.md` for `npm run build`, `check:server` and the test key
  - `docs/STATUS.md`
  - `data/README.md`, saying CLM-1901 is now seeded into the queue without its decision
- [ ] `npm run check` passes with `.env` moved out of the way. The results are reported and the phase is committed.
