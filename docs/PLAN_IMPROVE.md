# Plan: an improver for the claim agent, and handlers who sign in

The plan for `docs/IMPROVE.md`, on branch `week2day5-sarvjot`, made from `week2day4-sarvjot`.

SIDENOTE: For consistency with the course, please read `labs/week2day5.ipynb` and build the judge, the configuration's versions and the improver in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

## What stays ours

- **The limit stays at $800.** The brief's Settings page starts the approval limit at $1,000. Ours is seeded from `payout_approval_limit` in `data/company.json`, which is $800. From now on it's a setting that Dana can change on the Settings page. The claims manual keeps its mention of $1,000, as the brief says.
- **The live view stays a board**, now behind the sign-in. Its cards and stamps don't change.
- **The code stays in small modules.** The new modules are named below, and `backend/api.py` stays the app.
- **The labs stay out of every commit.**

## Where the brief's notes don't match our build

The brief's "Notes from our last build" describe Ed's swarm. Ours differs, so here is how each note maps onto our code:

| The note says | In our build |
|---|---|
| `agent/api.py`, the claim agent's client | `agent/client.py` (`backend()` and `reply()`). The improver gets its own client, `agent/improver_client.py`. A test checks that `agent/client.py` and the claim agent's tools never name the scores, the evaluations, the rounds or the handlers' decisions. |
| `test_the_agent_cant_read_the_scoreboard` | We have no such test. We add one (above). |
| The one-run rule is a `threading.Lock` in `agent/service.py` | Ours is `busy`, also a `threading.Lock` in `agent/service.py`. We keep it, and refusals now name what is running. Claims resumed after a sign-off aren't held by it: their claim leases keep them apart, as they do today. |
| `agent/api.py` waits 30 seconds for the backend | Ours waits 150 seconds (`agent/client.TIMEOUT`). Grading in `finish_run` is held under 20 seconds anyway. |
| The service records no reasoning effort as `none` | Ours does too (`model.describe()`). It becomes `default`. |
| `SignOffForm.tsx` and `sign_off_claim` take a `handler_id` | Ours is the `SignOff` component in `ClaimView.tsx` and `POST /api/claims/{id}/sign-off` (`sign_off`). Both give way to the signed-in handler. |
| The `handlers` table has no email column | Ours keeps each handler as JSON, which already holds the email from `data/handlers.json`. We add an `email` column so the backend can find a handler by it. |
| `start_dispatch`, `start_evaluation`, `sign_off_claim` | Ours are `start_dispatch`, `start_evaluation` and `sign_off`, plus `run_claim` ("Run the agent"), which is a handler's action too. |
| `dashboard/vite.config.ts` is Vitest's config too | The same in ours. |
| `styles.css` sets dark mode from `prefers-color-scheme` alone | The same in ours. |
| Time per claim was 12.4 seconds at N=3 and 21.4 at N=25 | Ours was 24 to 59 seconds at N=3 and 71 to 94 at N=25, with slower round trips to Supabase. This matters for the time tolerance (decision 8). |

## How it will work

### Sign-in (phase 1)

- **The dashboard** signs in with `@supabase/supabase-js` and `signInWithPassword`, reading `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`, in a module of its own, `dashboard/src/auth.ts`.
  - Every page sits behind a sign-in page: email, password and the error, with no sign-up.
  - The header shows the handler's name and role, with "Sign out".
  - Every request that changes something sends `Authorization: Bearer <access token>`, through one function in `api.ts`.
- **The backend** checks the token in `backend/auth.py`:
  - with PyJWT's `PyJWKClient` on `<VITE_SUPABASE_URL>/auth/v1/.well-known/jwks.json` and the audience `authenticated` (`uv add "pyjwt[crypto]"`, since today it's only in the `server` group)
  - the Supabase address is read once from the environment
  - it finds the handler by the token's email, and refuses a missing or bad token with a 401
  - it refuses a handler who isn't allowed with a 403 that says why, such as "Marcus Oyelaran can't sign off payouts over the limit"
- **The handler actions** take a `SignedIn` dependency:
  - sign-off
  - "Run the agent"
  - starting a dispatch, an evaluation or a round
  - stopping a round
  - approving or rejecting a proposal
  - changing a setting

  Of those, a sign-off, anything to do with a round and a change to a setting also need `can_approve_over_limit`. The agent's own calls stay open until Week 3, as the brief says.
- **A sign-off** records the signed-in handler. `POST /api/claims/{id}/sign-off` takes no body, and the form loses its list of handlers.
  - Marcus and Priya get `can_approve_over_limit: false` in `data/handlers.json`.
  - When one of them looks at a held payout, the claim page says "Only a handler who can sign off payouts over the limit can sign this off", and the backend refuses too.
- **The tests:**
  - Unit tests sign tokens with a test key and point the JWKS client at it.
  - The end-to-end tests get `e2e/auth-standin.ts`, which signs ES256 tokens with a key of its own, answers `/auth/v1/token`, `/auth/v1/user`, `/auth/v1/logout` and the JWKS path, and answers the browser's CORS checks.
  - The tests set their own `VITE_SUPABASE_URL`. `envDir` in `dashboard/vite.config.ts` points `npm run dev` at the root `.env`, and the tests set their values explicitly.
  - Every end-to-end spec signs in, through one helper.

### The configuration's versions (phase 2)

- **Tables:**
  - `config_versions`: version, instructions, model, reasoning, what changed, the reason, proposed by, approved by, approved at, and current or not
  - `recipe_versions`: version, recipe, reason, proposed by, approved by, approved at
- **Seeding:**
  - configuration version 1 is the instructions in `backend/instructions/claim.md`, with `openai/gpt-6-luna` at `low`
  - recipe version 1 is the lab's recipe, in `backend/instructions/recipe.md`
  - "proposed by" is "seed"
- **The claim agent gets its version** from `GET /api/configuration/versions/{n}`: instructions, model and reasoning only, never a score. `claim.build` makes the model from the version, where today it uses `agent/model.py`'s default.
  - A dispatch, an evaluation from the Scoreboard and "Run the agent" use the current version.
  - A round's evaluation uses the version under test.
  - `runs` gains `version` and `round_id`, and `Run` carries both to `claim.work`.
- **With `MODEL_NAME` set** (the free route):
  - the configuration's model is that model, at effort `default` with a price of 0
  - it's the only model allowed
  - the judge isn't called
  - `model.describe()` reports `default` in place of `none`
- **The Configuration page** (`#/configuration`) takes the place of the Instructions page, which redirects to it. It shows:
  - the current version
  - every version, with its held-out scores, what changed, the reason, who proposed and approved it and when
  - a diff of any version against the one before
- **Diffs** come from the backend, made with Python's `difflib` as in the lab. One `DiffView` component draws the additions and removals in colour, for versions and recipes alike.
- **A version's scores** are the averages of the whole-set evaluations that rounds ran on it, per set (`backend/versions.py`). An evaluation started on the Scoreboard doesn't count, nor does a tiny one.

### Settings (phase 2)

- **The table:** `settings` holds the values, and `setting_changes` holds who changed what, when, from what and to what. They're seeded from:
  - `data/company.json` for the approval limit ($800)
  - the new `data/settings.json` for the rest, with the lab's values:
    - objectives: accuracy 0.6, grade 1.0
    - noise: accuracy 0.1, grade 0.15, cost per claim 0.15, time per claim 0.15
    - tolerance: accuracy 0.1, grade 0.15, cost per claim 1.0, time per claim 0.25
    - spending limit for a round: $0.50
    - agents at once: 25
- **The models allowed** are in the new `data/models.json`: the lab's three models, with their reasoning efforts and their prices as numbers in dollars per million input and output tokens. The Settings page shows them, and nobody can change them there.
- **Every part reads settings from the backend.** The approval limit moves out of `rules.APPROVAL_LIMIT` into the settings table. Each decision records the limit it was decided under, so a new limit applies to the decisions recorded after it, and a payment checks the limit on its own decision.
- **The Settings page** (`#/settings`):
  - every handler sees it
  - Dana changes values in a form, with the dashboard's own confirm dialog
  - Marcus and Priya see it read only, with a line saying why
  - it holds the appearance: light, dark or as the computer, kept in `localStorage`, setting `data-theme` on the page
  - `styles.css` gains the colours for `[data-theme="dark"]` and `[data-theme="light"]` beside the media query

### The judge (phase 3)

- **`backend/judge.py`** is the only place that calls Jev, `typesafe/jev-1.13`, through the `openrouter` package's `alpha.decisions.create`. It uses the lab's rubric and three questions, with `server_url` read once from the environment (default `https://openrouter.ai`), `timeout_ms=10_000` and retries turned off.
- **The state** is the handler's decision, reason and reference, beside the agent's decision, reasons and policy section.
- **The answers:**
  - the grade is Jev's `score`, from 0 to 3
  - the letter is the level with the highest probability, never the score rounded
  - the two checks are kept as probabilities, and shown as yes or no at 0.5
- **Seeding** stores each label's `reason` and `reference` in `handler_decisions`.
- **Grading happens as an evaluation finishes:**
  - `POST /api/runs/{id}/finish` grades the evaluation's claims in parallel, under 20 seconds in all, and stores each in `judgements`: run, claim, grade, letter, the two checks and cost
  - a claim the agent didn't decide gets an F without asking the judge
  - a claim the judge couldn't grade shows as not graded and is left out of the average
  - the judge's cost is recorded with the evaluation, apart from the claim agent's cost
- **The scoreboard** adds the average grade and the judge's cost, and an evaluation's page shows each claim's grade with its two checks.
- **The tests** stub the judge's single call. The end-to-end tests get `e2e/judge-standin.ts`, which answers the Decisions endpoint with fixed grades.

### The improver (phase 4)

- **`agent/improver.py`**, the agent's sixth part:
  - `create_agent` on GPT-6 Luna at medium effort
  - `parallel_tool_calls=False` in its model settings
  - `ModelCallLimitMiddleware` caps its model calls for each round (20)
  - `HumanInTheLoopMiddleware` on `propose_change` and `propose_recipe`
  - a `PostgresSaver` of its own on the shared pool, with `durability="sync"`, and a new thread for each round (`round-<id>-<random>`)
- **Its instructions**, in `backend/instructions/improver.md`, are written as goals and wrap the recipe. They say:
  - what the claim agent works from: its instructions, the policy wording and claims manual through its tools, the claim, the policy and the customer's earlier claims, and its tools for searching and reading sections and working out a payout
  - that a change never names a claim
  - that the recipe is data it follows
- **Its tools** are the lab's four, under the lab's names. They reach the backend only through `agent/improver_client.py`:
  - `read_results`: the improver's view, from `GET /api/rounds/{id}/view`. It has:
    - the current version
    - its averages on both sets
    - from its latest evaluation-set run: the wrong claims and the five right ones with the lowest grades, each with the handler's decision and reason beside the agent's, and the judge's grade and checks
    - the earlier rounds
    - the round's settings and our rule
    - what's left of the spending limit
    - the models allowed

    From the held-out set it has only the scores.
  - `propose_change`: a proposal outside the models allowed is refused back to the improver without reaching a handler. Otherwise the middleware pauses, and the service records the proposal with the backend.
  - `run_evaluation`: refused when the estimate is over what's left of the limit. Otherwise it runs the version under test once on the evaluation set and twice on the held-out set, through the dispatcher in this process, in a fresh `contextvars.Context`. Then it asks the backend for the verdict.
  - `propose_recipe`: paused the same way.
- **The round's work in the agent's service:**
  - `POST /rounds` starts a round, `POST /rounds/{id}/decision {type, message, handler_id}` approves or rejects, and `POST /rounds/{id}/stop` stops one
  - a round's stretch of work holds `busy`, so its evaluations are part of it
  - first it runs the current version's missing whole-set evaluations (1 on the evaluation set and 2 on the held-out set), then it invokes the improver until it pauses or finishes
  - before resuming the improver, the service records the decision and the handler with the backend
  - at startup it marks a round that was working as stopped, and leaves a round waiting for approval as it is
- **The backend owns a round's record** (`backend/rounds.py` and `backend/routes/rounds.py`):
  - `rounds`: id, thread, recipe version, a copy of the settings, stage and progress (such as "evaluations, 2 of 3"), the proposal waiting, the version tried, the improver's reason, the held-out scores before and after, the verdict and why, status, and the times
  - `round_events`: each approval or rejection, with the handler, when and the reason
  - the dashboard's `POST /api/rounds`, `/api/rounds/{id}/stop` and `/api/rounds/{id}/decision` check the handler, then ask the service, passing on its refusal
  - the service's own writes go through `POST /api/rounds/{id}/...` routes, which refuse anything once the round is stopped
- **The rule** (`backend/verdict.py`) mirrors the lab's `compare` and `keep_or_roll_back`, with the round's own copy of the settings:
  - cost and time are compared as a fraction of the old value, accuracy and the grade as a difference
  - a version without a grade is rolled back, and so is a version whose evaluations were stopped or that the round couldn't afford
  - a kept version becomes the current version
- **The spending limit:**
  - **Spent** is the improver's calls (`usage` with `round_id`), the claim agent's cost and the judge's cost in all the round's evaluations, the first ones included.
  - **The estimate** for an evaluation is its claims times the highest cost per claim seen so far for its model. For a model with no runs, it's the current model's, scaled by the larger of the input and output price ratios.
  - **Once a round has spent its limit**, the dispatcher starts no new claim in its evaluations. A claim already started runs to its end. An evaluation cut short shows as stopped.
- **One thing at a time:** a start, an approval or a rejection while something else is running is refused, naming what's running, such as "Dispatch 7 is running". A round waiting for a handler holds nothing, so dispatches and evaluations can run meanwhile.
- **Stopping a round:**
  - before its verdict, it leaves the current version as it was
  - after its verdict, it keeps it
  - the service starts no more claims or model calls for it, and lets go of `busy` when the work in hand ends
- **Langfuse:**
  - the improver's work in a round is one session, named after the round's thread
  - the claims of its evaluations are tagged with the round as well as their run, such as `["evaluation-14", "round-3"]`
- **Cost:** the improver's model calls are recorded with their round, from OpenRouter's `usage.cost`.

### The Improvement page (phase 5)

- **The page** (`#/improvement`) shows:
  - "Start a round" and "Stop the round"
  - where the open round has got to: the first evaluations (1, 2 or 3 of 3), the improver working, a change waiting, the evaluations (1, 2 or 3 of 3), the verdict, a recipe waiting, finished or stopped
  - a proposal waiting, with the instructions as a diff, the model and effort before and after, and the reason, with "Approve" and "Reject" (a rejection needs a reason)
  - the rounds so far, newest first: the version tried, the held-out scores before and after, the verdict and why, who approved what, and the cost
  - an SVG chart of each tried version's held-out accuracy and grade, with no new library
  - the recipe's versions, with the same diff view
- **Marcus and Priya** see it all, with a line saying why they can't act, and the backend refuses them too.

### The look of the dashboard (phase 6)

- **Shared pieces:**
  - `PageHeader`: a title and a line that says what the page is for
  - `ConfirmDialog`, the dashboard's own
  - `EmptyState`, `LoadingState` and `ErrorState`, each saying what to do next
  - `Badge`, a status with a colour and a word
  - one `Button` style
  - numbers right-aligned with their units
  - space kept for data while it loads, so nothing jumps as a page refreshes
- **Navigation:** Queue, Scoreboard, Improvement, Configuration and Settings, showing where you are, with the handler and "Sign out" on the right.
- **The existing pages** get the same header, spacing, tables and buttons, and change nothing about how they work.
- Everything follows `docs/BRAND.md`, in light and dark, on a laptop screen.

## Decisions for your review

1. **The approval limit starts at $800**, our figure, not the brief's $1,000.
2. **Our CODE_STANDARDS has no rules 7, 13 or 14.** The brief's version has them. I'd add three rules to ours:
   - each part of the agent reaches the backend only through its own client module, and the claim agent's client never reaches the scores or the handlers' decisions
   - the dashboard reaches Supabase only through `dashboard/src/auth.ts`
   - an agent's instructions are written as goals, with data such as the recipe kept apart from them

   The agent's parts stay listed in `docs/TECH_STACK.md`, as before.
3. **"Run the agent" on a claim page also needs a signed-in handler**, since it's a handler's action. The brief's list doesn't name it.
4. **A decision records the approval limit it was decided under.** So a held payout stays held after the limit is raised, and a new limit applies only to the decisions recorded after it.
5. **The Instructions page becomes the Configuration page**, and `#/instructions` redirects there.
6. **The improver's evaluations run in the agent's service through our dispatcher**, at N set by the settings (25).
7. **There are six phases.** The look of the dashboard and the live runs share the last one, as the brief orders them.
8. **The time tolerance stays at the lab's 0.25.** Our time per claim moves a lot with Supabase's round trips, which were 24 to 94 seconds a claim in the last live run. So a version may be rolled back as "time per claim got worse" when nothing changed but the network. The live runs will report how far version 1's two held-out runs differ, and you can widen the tolerance on the Settings page if you see it happen.

## Before the live runs: setup

Done on 4 November 2026, and checked: Dana Whitfield, Marcus Oyelaran and Priya Raman each sign in through Supabase Auth with `HANDLER_PASSWORD`, sign-ups are off, and Supabase signs with ES256 keys, published at its JWKS address. A credit limit on the OpenRouter key is optional, as the lab suggests.

## Phases

Each phase ends with its criteria ticked here, `docs/STATUS.md` updated and a commit.

### Phase 1: handlers sign in

- `backend/auth.py`, the `SignedIn` dependency on every handler action, and the `email` column.
- `can_approve_over_limit` set to false for Marcus and Priya.
- A sign-off records the signed-in handler.
- The sign-in page, the header and `auth.ts`.
- The Auth stand-in, and every end-to-end spec signing in.

Success criteria:

- [x] A test shows every handler action refused with a 401 without a token, with a bad token, with an expired token and with a token for an email that isn't a handler.
- [x] A test shows a sign-off over the limit refused with a 403 for Marcus, and recorded for Dana with her id and the time.
- [x] A test shows `/openapi.json` still has an `operation_id`, a one-line docstring and no optional inputs for every operation.
- [x] Vitest checks the sign-in page (success, a wrong password, and no sign-up), the header with the name and "Sign out", and that an action sends the bearer token.
- [x] Vitest checks that Marcus sees why he can't sign off a held payout, with no sign-off button.
- [x] Every end-to-end spec signs in through the stand-in, and the sign-off test records the signed-in handler.
- [x] `npm run check` passes with `.env` moved out of the way.

### Phase 2: the configuration's versions and the settings

- `config_versions`, `recipe_versions`, `settings` and `setting_changes`, with their seeds, and the new `data/settings.json` and `data/models.json`.
- The claim agent built from its run's version. `runs.version` and `runs.round_id`.
- The approval limit read from the settings, and recorded on each decision.
- The Configuration page with `DiffView`, the Settings page, `ConfirmDialog` and the theme switch.

Success criteria:

- [x] A test shows a dispatch and an evaluation each record the version they used, and the claim agent built with that version's instructions, model and effort.
- [x] A test shows `GET /api/configuration/versions/1` holds no score, and the claim agent's client and tools still name none of the scores, evaluations, rounds or handlers' decisions.
- [x] A test shows a version's scores counting only the whole-set evaluations its rounds ran.
- [x] A test shows a new approval limit applying to the next decision, a payout already held staying held, and the change recorded with who and when.
- [x] A test shows a settings change refused for Marcus with a 403, and for anyone signed out with a 401.
- [x] A test of `difflib`'s diff on two versions.
- [x] With `MODEL_NAME` set, a test shows that model is the only one allowed, at `default` with a price of 0.
- [x] Vitest checks the Configuration page (versions, the diff in colour), the Settings page (Dana edits after a confirmation, Marcus reads), and the theme switch setting `data-theme` and remembering it.
- [x] An end-to-end test changes a setting and switches the theme.
- [x] `npm run check` passes with `.env` moved out of the way.

### Phase 3: the judge

- `backend/judge.py`, the reasons and references seeded, grading as an evaluation finishes, the `judgements` table, the judge's cost, and the grade on the scoreboard and the evaluation's page.
- The judge's stand-in.

Success criteria:

- [x] A test on a stub judge shows the letter is the most likely level, not the score rounded (for example, probabilities that make the score 1.6 but C the most likely).
- [x] A test shows an undecided claim graded F without a call, and an ungraded claim (a timeout) left out of the average.
- [x] A test shows grading 25 claims in parallel finishes inside 20 seconds when each stubbed call takes 2 seconds.
- [x] A test shows the judge's cost recorded with the evaluation, apart from the claim agent's.
- [x] A test shows the judge's address read once from the environment and passed as `server_url`, with retries off and a 10-second timeout.
- [x] Vitest checks the grade on the scoreboard and each claim's grade with its two checks.
- [x] `npm run check` passes with `.env` moved out of the way.

### Phase 4: the improver

- `agent/improver.py`, `agent/improver_client.py`, `backend/instructions/improver.md`, and the rounds in the service and the backend.
- `backend/verdict.py`, the spending limit, the one-run rule naming what's running, and the Langfuse sessions and tags.

Success criteria, all on a stub model and a stub judge:

- [x] Tests of the rule, with the measures worked out by hand: a version kept, one rolled back for missing an objective, one for a measure worse than its tolerance, one where nothing beat the noise, and one with no grade. Cost and time are compared as fractions, accuracy and the grade as differences.
- [x] A test shows the improver's view holds the held-out set's scores and nothing else from it: no claim ids, decisions or reasons.
- [x] A test plays a round from start to finish: the first evaluations, a proposal that changes nothing until approved, a rejection whose reason reaches the improver, a second proposal approved, the evaluations, the verdict, and a recipe proposal approved.
- [x] A test shows a proposal outside the models allowed going back to the improver without a pause.
- [x] A test shows an approval refused while a dispatch runs, with a message naming the dispatch, and nothing recorded.
- [x] A test shows an evaluation refused when its estimate is over what's left, and one cut short by the limit shown as stopped, with its version rolled back.
- [x] A test shows a round stopped before its verdict leaving the current version as it was, and one stopped after keeping it.
- [x] A test shows a round keeping its own settings when the settings change.
- [x] A test shows a round waiting for approval survives a restart of the service, and a round that was working is marked stopped.
- [x] A test shows the improver's model calls recorded with the round, and its trace config with the round's session and tags.
- [x] `npm run check:python` passes, with coverage at 80% or more.

### Phase 5: the Improvement page

- The page, the stages as they happen, the proposal with its diff, the rounds, the chart and the recipes.

Success criteria:

- [x] Vitest checks each stage of a round as it shows, a proposal's diff with the model and effort before and after, approve with a confirmation, reject with a reason, the rounds newest first, the chart's points and the recipes.
- [x] Vitest checks that Marcus sees why he can't start, stop, approve or reject.
- [x] An end-to-end test starts a round (the stand-in receives it), and approves a proposal that the test plays out through the API.
- [x] `npm run check` passes with `.env` moved out of the way.

### Phase 6: the look of the dashboard, the live runs and the handover

- `PageHeader`, the states, `Badge`, `Button`, and the existing pages brought up to the same standard.
- Then one `npm run seed` and the live runs below, on the default model.

Success criteria:

- [x] Vitest checks the loading, empty and error states on each page, and that a refresh keeps the layout's space.
- [x] Signed in as Dana through the Playwright MCP server (or a script on Playwright's library if the server won't connect), two rounds run from the Improvement page:
  - [x] the first proposal rejected with a reason, then the next approved, and the rest approved
  - [x] each stage shown as it happens
  - [x] afterwards, the scores before and after, the verdict and the cost
- [x] The Configuration page shows the versions and their diffs.
- [x] Through Langfuse's API, each round's improver traces are found in one session.
- [x] The report says how far version 1's two held-out runs differed on each measure, beside the noise and the tolerance.
- [x] A dispatch at N=25 runs on the current version.
- [x] Signed in as Marcus, a payout waiting for sign-off can't be signed off and the settings can't be changed. Signed in as Dana, the same payout is signed off and paid.
- [x] Screenshots of every page in light and dark. A fresh subagent reviews them once, as a senior product designer would, against `docs/BRAND.md` and point 8 of the brief, and what it finds is fixed.
- [x] The report says what the live checks spent, which should be under $1.
- [x] `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` (decision 2), `docs/STATUS.md` and `data/README.md` describe the product as it now is.
- [x] `npm run check` passes with `.env` moved out of the way, and the results are reported.

Moving `.env` out of the way is a rename and back, and nothing reads it. Throughout, keys and the handlers' password stay in the environment of the processes that need them and are never printed.
