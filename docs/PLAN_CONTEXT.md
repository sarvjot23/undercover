# Plan: the context layer, memory and the Gateway for the claim agent

The plan for `docs/CONTEXT.md`, on branch `week3day3-sarvjot`, made from `week3day2-sarvjot`.

SIDENOTE: For consistency with the course, please read `labs/week3day3.ipynb`, which deploys the app and the context layer, creates the Gateway and the memory, and runs the agent against them, without running it. Where the notebook and this document differ, follow this document. Include this sidenote in your plan too.

The brief's five steps are phases 1 to 5, one each, with a commit at the end of each. Phase 6 reseeds once, does every live check, brings the documents up to date and reports what the checks spent. The live checks use the direct route with memory off, as the brief asks, so nothing in this plan touches AWS. The Gateway route, the Gateway's refusals and the memory are covered by tests with stand-ins.

## What stays ours

- **The limit stays at $800**, a setting. The Gateway's Policy, at $1,000, comes with the deployment.
- **Small modules.** The new ones are named in each phase.
- **The decision's field names stay `reasons` and `policy_section`.** The brief's new fields take the data dictionary's names (`calculation`, `decided_by`, `manual_version`). Renaming the two old fields would change the judge, the scoring, the improver's view, the dashboard and the end-to-end tests for no gain. The notebook's Part 3 calls `record_decision` with `section` and `reason`. On our build that call is still refused with a 422, which is what the cell shows, but the message is about the missing fields.
- **The labs stay out of every commit.**

## Where the brief's notes don't match our build

| The note says | In our build |
|---|---|
| The tools are in `agent/tools.py` on `agent/api.py` and `agent/connection.py`, with a `ClaimContext` read through `ToolRuntime` | Our tools are in `agent/tools.py`, and each one calls `agent/client.py`. The model passes the claim's id today. We add a `ClaimContext` (the claim, its policy, its customer, the version, the kind of run, the route), made when the claim's graph is built. Each claim's tools are made for it and read it there, rather than through `ToolRuntime`, which needs nothing passed on each invoke; so the model passes no id. |
| The claim graph is in `agent/harness.py` with `screen`, `refer`, `ToolNode(handle_tool_errors=refusal, wrap_tool_call=record_result)` and `pay`, built by `claim_graphs` | Ours is `agent/graph.py`, with the nodes `check`, `agent`, `record`, `tools`, `sign_off`, `pay` and `close`, and `record_tool_result` wrapping each tool. It's built per claim by `build` in `agent/claim.py`, which knows the run and its kind. |
| The documents are in a documents table, and the claim agent's instructions end with their contents | We have no documents table. `backend/documents.py` reads `data/policy_wording.md` and `data/claims_manual.md` on first use, and our instructions don't include the documents: the agent reads sections with its tools. We add a `documents` table, which seeding fills from `context/`, with each document's version and source. It serves the wording to the dashboard and gives a decision the manual's version. Our instructions keep not including the documents, so "still" holds as it is in our build. |
| Seeding reads `data/plans.json` in `backend/database.py` | Ours is `seed` in `backend/db.py`. `backend/payout.py` also loads `data/plans.json` when it's imported. Both move to the plans table, seeded from `context/plans.yaml`, so the app reads no plan file at run time. |
| The app's operations are in `backend/main.py` | Ours are in `backend/routes/*.py`. `backend/main.py` only adds the Lambda handler. |
| The claim page is `ClaimPage.tsx` with `StepList.tsx`, `SectionsRead.tsx` and `DecisionPanel.tsx` | Ours is `dashboard/src/ClaimView.tsx`, with `Steps.tsx`. Its `Reads` panel is our Sections read, and the decision and the sign-off are in `ClaimView.tsx`. |
| The app has `search_documents` and `read_section` | We also have `list_sections`, which the agent uses today. All three go with the documents router. The model then finds sections with `search_documents` and reads them with `read_section` in the context layer. |

### Choices to note before you approve

1. **One module for each route**, as the brief asks for `docs/CODE_STANDARDS.md`. `agent/gateway.py` is the Gateway route: an MCP client over streamable HTTP, signed with SigV4 for `bedrock-agentcore`. `agent/direct.py` is the direct route: the app through `agent/client.py` with the key, and the context layer over MCP unsigned. Both offer the same `call(target, operation, arguments)`, which returns the answer's text or raises a `Refused` that says who refused (the app, the context layer or the Gateway). `agent/tools.py` builds the model's tools on whichever route the graph was built with. The bookkeeping stays on `agent/client.py`.
2. **A sync bridge for the async MCP tools** (`agent/mcp_bridge.py`). Each call runs on a new event loop of its own, which it closes without setting it as the thread's loop. That avoids the trap in the brief's note, where `asyncio.run` leaves the main thread with no loop for Mangum. The Gateway is stateless, so a session for each call is fine.
3. **The decision's calculation** is kept in a new `calculations` table, one row for each claim and attempt, replaced by each `calculate_payout`. "For this attempt" uses the claim's `attempts` column, so a claim sent back to the queue needs a fresh calculation.
4. **A lookup's step holds structured detail.** Steps get a `detail` column (JSON, empty for the old kinds). A lookup step's detail is what was looked up, its file, and the file's system, owner and review date. A search of the documents has one entry for each file it found sections in. The dashboard groups the Context used panel by file from this detail, not by parsing the text.
5. **When the Gateway refuses a payment**, a new operation, `POST /api/claims/{id}/hold` (`hold_payment`, the agent's key only, not in the agent's API document), moves an approved, unpaid claim in progress to waiting for sign-off. It records the Gateway's reason on the decision (`payment_refused`). The graph's `pay` then goes to `sign_off`, and a handler's sign-off pays as it does today. The sign-off panel shows the Gateway's refusal in place of "over the approval limit".
6. **The memory saves in a node of its own, `remember`.** It sits between the decision and what follows it (`pay`, `sign_off` or `close`), so after a restart, or when a signed-off claim resumes at `sign_off`, it runs once and no more.

---

## Phase 1: Tools from the Gateway

**What it builds.**

- `agent/gateway.py` and `agent/direct.py` as above, with `agent/mcp_bridge.py`. `agent/routes.py` picks the route when a claim graph is built. With `UNDERCOVER_GATEWAY_URL` set, it uses the Gateway. Without it, it uses the direct route, with the context layer at `UNDERCOVER_CONTEXT`, or `http://127.0.0.1:8006/mcp` when that isn't set. It reads the settings at that moment, not when it's imported.
- The Gateway route signs every request with the credentials and region the AWS CLI uses (`boto3.Session()`), with an `httpx.Auth` class like the notebook's. It calls each tool with the `mcp` package's `ClientSession` directly, which `MultiServerMCPClient` wraps: an error result is the app's refusal, with the app's answer, and an `McpError` is the Gateway's own. The `McpError` is caught inside the session, because raised through the transport's task group it comes out wrapped in an exception group.
- The model's app tools are `get_claim`, `get_policy`, `get_claim_history`, `calculate_payout` and `record_decision`. They're thin and take no claim, policy or customer id. They fill these in from `ClaimContext`, which is filled from the claim when the graph is built. `get_claim` gives the app's own JSON text on both routes, the same text the security check reads. Phase 2 adds the context layer's tools to the same list.
- `pay` goes through the route too, as `pay_claim` (`undercover-app___pay_claim` on the Gateway). An `McpError` there calls `hold_payment` and goes to `sign_off`. Any other refusal still fails as it does today.
- A refusal from the app or the Gateway reaches the model as "Refused by the app: …" or "Refused by the Gateway: …". It is never a plain answer. The step records it with who refused (phase 5 gives it a step kind of its own).
- `hold_payment` in `backend/routes/claims.py` moves only an approved, unpaid claim in progress, and gives 409 for anything else. The decisions table gets `payment_refused`.
- The bookkeeping stays direct with the key: the start, the steps, the usage, the work times, the failures, the check's read of the claim and its referral, the runs, the versions and the improver.
- `uv run -m agent` still loads `.env` first, and the route is read when the graph is built, so the command line sees the settings.

- [x] `agent/tests/test_routes.py`, with a stand-in Gateway (a small MCP server in the test that names its tools `undercover-app___get_claim` and the rest, passing calls on to the test app):
  - on the Gateway route, the model's tools have the same names and inputs as on the direct route, and none takes a claim, policy or customer id
  - `get_claim` gives the same text on both routes
  - a refusal by the app comes back as "Refused by the app" on each route
  - a tool the Gateway refuses (`McpError`) reaches the model as a refusal by the Gateway and is recorded on the claim, and the work carries on to a decision
  - a payment the Gateway refuses leaves the claim waiting for sign-off with the Gateway's reason, and Dana's sign-off then pays it
- [x] `backend/tests/test_rules.py`: `hold_payment` moves an approved, unpaid claim in progress to `awaiting_sign_off`, gives 409 on a paid claim, a decline and a claim waiting, and 401 without the key
- [x] The settings are read when a graph is built: a test sets `UNDERCOVER_GATEWAY_URL` after `agent.routes` is imported and gets the Gateway route
- [x] The existing agent tests pass on the direct route with the new tools
- [x] `npm run check` passes, and the commit goes through the pre-commit hook

## Phase 2: The context layer

**What it builds.**

- `context/server.py`, a FastMCP server (`mcp` 1.30) with `stateless_http=True` and `json_response=True`, served at `/mcp`. It has seven read-only tools, each with a one-line docstring and no optional inputs: `lookup_term(term)`, `describe_fields(record)`, `get_plan(plan)`, `get_claim_rules()`, `search_reference_data(query)`, `search_documents(query)` and `read_section(document, number)`. Each answer is JSON that names its file with the file's source: system, owner and review date. A document search names the file of each section it finds.
- `context/files.py` reads the seven files once, at import. It splits each document at `^## (\d+)\. (.+)$` into sections tagged with the document, number and title, and keeps the front matter as the document's source and version. The front matter is never part of a section.
- `context/__main__.py`: `uv run -m context` serves it at `http://127.0.0.1:8006/mcp` with uvicorn. `npm run dev` gets `dev:context`.
- On Lambda, `handler(event, context)` builds a fresh server for each request with DNS rebinding protection off, and runs it under `Mangum(..., lifespan="auto")`, as the brief's note says.
- `pyproject.toml` gets `pyyaml`, `mcp` (pinned to `uv.lock`'s version) and a `context` group: `mcp`, `pyyaml` and `mangum`. `pyyaml` joins the `server` group too, since seeding imports it. `npm run check:context` imports `context.server` with only that group installed, and `npm run check` runs it. Ruff, pyright, pytest and coverage take in `context/`.
- The app: seeding reads `context/plans.yaml` into the plans table (each plan with the benefits the deductible applies to and the add-ons), and the two documents into a new `documents` table with their version and source. `backend/payout.py` reads its plan from the table. `GET /api/policy-wording` reads the table. The documents router and `backend/documents.py` go, and the product no longer reads `data/plans.json` or the two documents in `data/`, which stay as they are.
- `backend/agent_api.py` has six operations: `get_claim`, `get_policy`, `get_claim_history`, `calculate_payout`, `record_decision` and `pay_claim`.
- The model's tools add the context layer's seven tools, from the route (`undercover-context___…` on the Gateway). `list_sections` goes. `backend/instructions/claim.md` changes only as far as the tools it names; phase 4 rewrites what it works from.

- [x] `context/tests/test_server.py` calls each tool against the real files in `context/`: a term in any case, an unknown term (with the list of terms), each record's fields, each plan, the claim rules, a reference search with two words in mixed case, a document search naming each section's file, a section read, and a section that doesn't exist. Every answer names its file and source.
- [x] A test calls `context.server.handler` twice in one process with Function URL events and a Function URL's host: it lists the tools, then calls one. Both succeed.
- [x] `npm run check:context` passes, and so does `npm run check:server` with `pyyaml` in its group
- [x] `backend/tests/test_agent_api.py` expects exactly the six operations
- [x] Seeding: the plans come from `plans.yaml` with the same limits as before, the documents table holds both documents with versions `2026.1` and `2026.2`, and a test shows that seeding opens no plan or document file in `data/`
- [x] The payout tests pass unchanged, on plans from the table
- [x] `npm run check` passes, and the commit goes through the pre-commit hook

## Phase 3: A complete decision record

**What it builds.**

- `calculate_payout` stores its lines and payout in `calculations` for the claim's current attempt.
- `record_decision` takes `decided_by` as well. The agent fills it in, and the model never sees it: "UnderCover Agent, version 3" from the version the graph was built on, or "Security check" for the check's referrals.
- Section 14's checks, each a 422 whose detail names "Claims manual section 14" and says what's missing. These are our own messages, a plain string rather than Pydantic's list. The request's checks (a blank reason, section or maker, an approval paying nothing, a decline or referral paying something) run before the claim is looked at. The new check is that an approval needs a calculation for this attempt and a payout equal to it.
- The decisions table gets `calculation` (JSON, empty for a decline or referral), `decided_by` and `manual_version`, from the documents table. `decided_at` is already there, and a sign-off still adds who and when.
- One shared helper in each test suite records a matching calculation first and sends the maker: `backend/tests/deciding.py`, which writes the calculation directly; `agent/tests/stubs.py`; and `e2e/api.ts`, which uses the brief's recipe on any claim (one `expense` line under `emergency_medical` for the payout plus the plan's deductible). The deductible is read from the claim's plan rather than from a first calculation of the payout alone, which gets it wrong for a payout smaller than the deductible. `agent/tests/stubs.py` scripts the same recipe as the model's `calculate_payout` call before its `record_decision`. Each test's own expected payouts stay as they are.

- [x] `backend/tests/test_decision_record.py`: each refusal names section 14 and what's missing (a blank reason, section or maker; an approval paying 0; a decline paying something; an approval with no calculation on file; one after a failure, whose old calculation is from an earlier attempt; an approval whose payout differs from the calculation). The request's checks get the same answer on a claim that doesn't exist.
- [x] A complete approval holds its calculation's lines and payout, the maker, when, and manual version `2026.2`. A decline and the security check's referral hold no calculation and their makers.
- [x] `agent/tests`: the agent's record says "UnderCover Agent, version N" for the version it worked on, and the check's referral says "Security check"
- [x] `npm run check` passes with the shared helpers, including the end-to-end tests, and the commit goes through the pre-commit hook

## Phase 4: Memory of each customer

**What it builds.**

- `agent/memory.py`. When `UNDERCOVER_MEMORY_ID` is set, the graph is compiled with `AgentCoreMemoryStore(memory_id=..., region_name=...)` from `langgraph-checkpoint-aws` (added to the dependencies), in the AWS CLI's region. The checkpoints stay in Supabase.
- `remember`, a node after the work: when the claim agent recorded the decision itself, it saves two events with the customer as the actor and the claim as the session. The first is the claim (summary, benefit, date and place, items) as a `HumanMessage`. The second is the decision, payout, section and reasons as an `AIMessage`. It runs in code every time, and records a memory save step. It saves nothing for a claim the check referred, or for an evaluation's copy. When AgentCore can't be reached, it logs a warning and the claim keeps its decision.
- `search_memory(query)`, a model tool described as searching what we remember about this claim's customer from their earlier claims. It searches only `("customers", <this customer>)`, gives each memory's text, and leaves out the summary of the claim it's working on. On an error it gives the model the error as a refusal. The tool is there only with memory on and outside an evaluation, decided when the graph is built from the run's kind.
- `backend/instructions/claim.md` names what the agent works from: the context layer's definitions, plans, rules, reference data and documents, and its memory of the customer, which adds to the claim history in our records (manual section 9) rather than replacing it. It stays written as goals. `backend/instructions/improver.md`'s sentence on the tools names the new ones.

- [x] `agent/tests/test_memory.py`, with a stand-in store: the two events after a decision, with the right actor, session and content (no story, no documents); nothing saved for a referral by the check or for an evaluation's copy; a search kept to the claim's customer that leaves out this claim's summary; no `search_memory` tool with memory off or in an evaluation; a store that fails leaves the decision and logs a warning, and a failed search is a refusal
- [x] `remember` runs once: work carried on after it saved saves nothing more
- [x] `npm run check` passes, and the commit goes through the pre-commit hook

## Phase 5: Every step on the claim page

**What it builds.**

- Step kinds in `backend/schemas.py`, `agent/` and `dashboard/src/api.ts`: `lookup` (in place of `read`), `memory_search`, `memory_save` and `refusal`, alongside the existing kinds. `GET /api/claims/{id}/steps` returns the `detail`.
- Tool calls are named as the Gateway names them on that route (`undercover-context___lookup_term`) and by their own names otherwise. The agent maps the model's names when it records the step.
- `Steps.tsx` shows each kind in plain words: a lookup says what was looked up and where it came from, a memory step says what it searched or saved, and a refusal stands out, labeled by who refused ("Refused by the Gateway", or the section 14 check's message, followed by the agent's next attempt).
- A Context used panel replaces "What the agent read". It lists each thing looked up once, grouped by file, with each file's system, owner and review date.
- The decision panel shows the whole record: the decision, payout, section, reasons, who decided and when, the manual's version, the calculation line by line, and any sign-off. The sign-off panel says when the Gateway refused the payment.
- In `docs/BRAND.md`'s look and the dashboard's plain words.

- [x] Vitest: each step kind, a refusal by the Gateway and one by section 14, the Context used panel grouping by file with sources and no repeats, the decision panel with a calculation, and the sign-off panel after a Gateway refusal
- [x] Python: the steps route returns the detail, and the agent records Gateway names on the Gateway route and its own names otherwise
- [x] An end-to-end test: a claim with lookups and a decision with a calculation shows the Context used panel and the calculation
- [x] `npm run check` passes with coverage of at least 80%, and the commit goes through the pre-commit hook

## Phase 6: The live checks and the handover

On the default model (GPT-6 Luna), after one `npm run seed`, with `npm run dev` running (backend, agent's service, context layer and dashboard), with no `UNDERCOVER_GATEWAY_URL` and no `UNDERCOVER_MEMORY_ID`.

- [ ] `npm run check` is green with `.env` moved out of the way
- [ ] The context layer answers on the direct route: a script lists its seven tools at `http://127.0.0.1:8006/mcp` and calls `lookup_term("unattended")`
- [ ] `uv run -m agent CLM-1005`, then `uv run -m agent CLM-1006`, each record a complete decision (calculation for an approval, maker, manual version), with no memory tool
- [ ] A dispatch at N=25 works the rest of the queue as before, and CLM-1901 is still referred by the check, with "Security check" as its maker
- [ ] An evaluation of the evaluation set's five tiny claims matches as before
- [ ] Dana Whitfield sees CLM-1005's and CLM-1006's pages: the tool calls, the lookups with where each came from, the Context used panel and the decision with its calculation. These are checked through the Playwright MCP server. If it doesn't connect, as last time, they're checked with Playwright's library from a script, said in the status.
- [ ] The run's cost from the recorded usage, reported
- [ ] `docs/SPEC.md`, `docs/TECH_STACK.md` (with the Deployment section's context layer and agent settings), `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` (one module for each route), `docs/STATUS.md` and `data/README.md` describe the product as it now is
- [ ] Every box in this plan is ticked, and each phase has its own commit

## Not in this plan

- Anything on AWS: the Lambda deployments, the Gateway and its Policy, and the Memory are the notebook's to create. `UNDERCOVER_GATEWAY_URL` and `UNDERCOVER_MEMORY_ID` turn on the same code later.
- Memory in evaluations, masking personal fields, and requesting documents from customers.
