# Plan: the UnderCover Copilot

The plan for `docs/COPILOT.md`, in six phases. Phase 1 builds the app's side, phases 2 to 4 build the Copilot itself, phase 5 builds the sidebar, and phase 6 runs the live checks and the handover. Each phase ends with its boxes ticked here, `docs/STATUS.md` updated and a commit of its own.

**The brief's sidenote, as it asks:** For consistency with the course, please build the Copilot the way the course has built its agents. Its agent loop is a LangGraph `StateGraph` written by hand: a node that calls the model, LangGraph's `ToolNode`, and the loop between them, with a `PostgresSaver` checkpointer, as in `labs/week2day3.ipynb` and the claim agent's graph. Please don't use LangChain's `create_agent` for it. The pause before a sign-off is an `interrupt()` in a node of its own, resumed with `Command(resume=...)`, since LangGraph runs an interrupted node again from the top when it resumes, as the claim agent's wait for a handler is a node of its own. The handler's sign-in reaches the graph and its tools in the graph's context (`context_schema`, read through `ToolRuntime`), never in the config, whose values LangGraph saves with each checkpoint. The Copilot is an AgentCore app of its own, made with `BedrockAgentCoreApp`, with one entrypoint and each turn's work registered as an async task, as the claim agent's AgentCore app does, and it is synchronous throughout, as the claim agent is. `labs/week3day4_lab1.ipynb` and `labs/undercoverlab/` show a pause in one Runtime session resumed in another. Its memory is `AgentCoreMemoryStore` as a LangGraph store, as the claim agent's memory is, with the Memory itself made as in `labs/week3day3.ipynb`. It reaches the context layer over MCP with `MultiServerMCPClient`, as in `labs/week2day2.ipynb`, and through the Gateway as in `labs/week3day2_lab2.ipynb` and `labs/week3day3.ipynb`. `labs/week3day4_lab2.ipynb` deploys the claim agent and points the app at it, and `labs/week3day5_lab1.ipynb` deploys the Copilot beside it, so please match the names that notebook uses. Read these notebooks without running them. Where a notebook and this document differ, follow this document.

**The names from `labs/week3day5_lab1.ipynb`:** the runtime `copilot` in `agentcore/agentcore.json` (deployed as `undercover_default_copilot`), the Memory `undercover_copilot_memory` with the strategies `handler_preferences` (`/handlers/{actorId}/preferences/`) and `handler_facts` (`/handlers/{actorId}/facts/`), the settings `UNDERCOVER_COPILOT_MEMORY_ID` in `agentcore/.env.local` and `UNDERCOVER_COPILOT_RUNTIME` on the app, and `{"operation": "health"}` answered `{"healthy": true}`. The handler's id is the actor (Dana is `HND-01`), and the conversation is the session.

**Built locally, with no AWS.** As agreed for the last three builds, nothing is deployed. The Copilot runs as its AgentCore app on 127.0.0.1:8081, on the direct route with memory off. The Runtime route (`UNDERCOVER_COPILOT_RUNTIME`), its Memory (`UNDERCOVER_COPILOT_MEMORY_ID`), the Gateway and the credentials from AgentCore Identity are built and tested with stand-ins only. Any check that needs AWS is marked **Skipped (no AWS)** rather than left out. Filling in the settings later turns them on with no rebuild.

## How the pieces fit

A handler types in the sidebar. The dashboard renews the sign-in if it has less than 20 minutes left, then posts the message to the app with it. The app records a new turn as working and sends the Copilot `{"operation": "turn", ...}` with the conversation's id, the turn's id, the message and the sign-in. It then replies to the dashboard at once. The Copilot asks the app who is signed in, then works the turn in its graph. It records each step with the app as it goes, all with the handler's sign-in. At the end it tells the app the answer, or the confirmation card when it pauses, or why it failed. The sidebar reads the conversation from the app about once a second while a turn is working.

The sign-in lives only in the payload and in the graph's context while a turn runs. It is never in the graph's state, its config, the steps, the memory or a log.

**Choices I've made, for your review:**

- **Where the Copilot's code goes:** in the `agent` package, as the brief says, in modules named `copilot_*`:
  - `agent/copilot_app.py`: the AgentCore app.
  - `agent/copilot_graph.py`: the graph.
  - `agent/copilot_tools.py`: its tools.
  - `agent/copilot_client.py`: its connection to the app, with the handler's sign-in.
  - `agent/copilot.md`: its instructions. They aren't versioned, so they don't belong in `backend/instructions/`, and Runtime's package holds only `runtime/` and `agent/`.
  - Its memory functions join `agent/memory.py`, which stays the one memory module.
- **The context layer through `MultiServerMCPClient`:** it loads the seven tools from the route: the context layer on the direct route, or only the `undercover-context___` tools on the Gateway, signed with the claim agent's `SigV4Auth`.
  - Its tools are async, so each call runs on a loop of its own through `agent/mcp_bridge.py`, wrapped as a synchronous tool. This keeps the Copilot synchronous.
  - `langchain-mcp-adapters` joins the `runtime` dependency group.
- **The sign-off is a tool, then a node.** The model calls `sign_off_claim`. The tool checks in code that the handler may sign off, and that the claim is in the queue and waiting for sign-off. It reads the card from our records and puts it in the state as the confirmation waiting.
  - After the tools, a confirmation waiting sends the graph to `confirm`, whose first line is `interrupt(card)`. On a resume it signs off as the handler, or not, and tells the model what happened.
  - Nothing before the `interrupt()` does anything, so running the node again on a resume repeats nothing.
- **The app keeps each turn and its steps** in three new tables: `conversations`, `copilot_turns` and `copilot_steps`. Seeding drops them, and the checkpoint tables already go. "Stopped" is worked out when a turn is read: a turn still working 20 minutes after it started or was answered.
- **A conversation's id** is `conv-` and 32 hex digits: 37 characters, which suits both Runtime's sessions and the Memory's.

## Phase 1: The app's side

Why: everything the Copilot reads or does goes through the app with the handler's sign-in, so the app needs the reads the Copilot lacks, the conversations and their turns, and a line to the Copilot. This phase builds all of it, tested with a stand-in Copilot.

- **New reads** (`backend/routes/records.py`, `backend/routes/evaluations.py`). Each takes a handler's sign-in, follows the API rules and has no optional inputs:
  - `GET /api/me` (`who_am_i`): the handler signed in, with their id, name, role and whether they can sign off over the limit. It takes a handler only, never the key.
  - `GET /api/customers/{customer_id}` (`get_customer`): who the customer is, their policies, their earlier claims and their claims in our queue, with where each stands.
  - `GET /api/customers/named/{name}` (`find_customers`): customers whose name contains the words given, ignoring case. This is new to the app.
  - `GET /api/payouts/over-limit` (`count_payouts_over_limit`): the approval limit, the claims in our queue paid more than it, and how many of those carry a handler's sign-off, in one read. It never counts an evaluation's copies.
  - `GET /api/evaluations/{run_id}/measures` (`get_evaluation_measures`): an evaluation's status and measures without its claims. The Copilot never reads the handlers' decisions.
- **The conversations** (`backend/db.py`, `backend/copilot.py` for the rules, `backend/routes/copilot.py` for the routes). Every route takes the handler's sign-in. A conversation that isn't theirs gets a 404, so nobody can see or carry on another handler's conversation.
  - The handler's routes, which the dashboard calls:
    - `POST /api/conversations` (`start_conversation`, with the first message): titled with that message.
    - `GET /api/conversations` (`list_conversations`): theirs, newest first.
    - `GET /api/conversations/{id}` (`get_conversation`): its turns, each with its message, status, answer, model calls, cost, time and steps, and the confirmation waiting.
    - `POST /api/conversations/{id}/messages` (`send_message`).
    - `POST /api/conversations/{id}/confirmation` (`answer_confirmation`, `{"confirmed": true|false}`).
  - The Copilot's routes, also with the handler's sign-in:
    - `PUT /api/conversations/{id}/turns/{turn}/steps/{key}` (`record_copilot_step`): a card's kind, tool, main input, state (working, done, refused, failed), seconds, what was asked and what came back (trimmed to 2,000 characters), and the files and owners of a context-layer answer. A step is recorded once by its key, then updated.
    - `POST .../turns/{turn}/finish` (`finish_turn`): the answer, model calls and cost.
    - `POST .../turns/{turn}/pause` (`pause_turn`): the card.
    - `POST .../turns/{turn}/fail` (`fail_turn`): why.
    - Each refuses a turn that isn't working with a 409.
  - **One turn at a time:** a new message is refused with a 409 while a turn is working ("The Copilot is still working on your last message") or waiting ("Answer the confirmation first"). The check and the new turn are one short transaction.
  - **A stopped turn:** one still working 20 minutes after it started or was answered reads as stopped, and a new message marks it stopped and goes ahead. A waiting turn is never stopped.
  - **A confirmation:** answering one moves the turn from waiting to working, in one conditional update, so it can be answered only once.
- **The line to the Copilot** (`backend/copilot_service.py`), shaped like `backend/agent_service.py` and reusing its `Answer`:
  - On the laptop, it posts to `{UNDERCOVER_COPILOT}/invocations` (`http://127.0.0.1:8081` by default) with no key.
  - With `UNDERCOVER_COPILOT_RUNTIME` set, it calls boto3's `invoke_agent_runtime` with the conversation's id as the session id. It retries a conflict (`ConflictException`) up to 4 times over about 6 seconds, since the call hasn't reached the Copilot. Otherwise it makes one attempt, with 5 seconds to connect and 20 to read.
  - A turn or an answer the Copilot didn't take is marked failed with the reason, so the handler can carry on.
- **Seeding** drops and makes the three tables like the rest, and the checkpoint tables already go, so `npm run seed` starts the conversations afresh.
- **What the Copilot sends:** the app never logs a payload, since it carries the sign-in.

Done when:

- [x] Tests: `who_am_i` answers the handler for a sign-in, and is refused (401) for the agent's key alone
- [x] Tests: `get_customer` gives a customer's policies, earlier claims and claims in the queue; `find_customers` finds by part of a name in any case and gives `[]` for none
- [x] Tests: `count_payouts_over_limit` gives 0 of 0 on a fresh seed, counts a claim paid over the limit with a sign-off, and leaves out an evaluation's copy
- [x] Tests: `get_evaluation_measures` has the measures and no claims or handlers' decisions
- [x] Tests: a message starts a turn and sends the stand-in Copilot the conversation, the turn, the message and the sign-in, with no `X-API-Key`; the Copilot's step, finish, pause and fail routes record what the sidebar reads
- [x] Tests: a second message while a turn works, or while it waits, is refused with a 409 and the reason
- [x] Tests: a turn working for over 20 minutes reads as stopped and a new message goes ahead; a turn waiting for over 20 minutes isn't stopped
- [x] Tests: another handler gets a 404 on someone else's conversation, its messages, its confirmation and its steps
- [x] Tests: a turn the Copilot didn't take is marked failed with the reason; the Runtime route (a stubbed boto3) uses the conversation's id as the session and retries a conflict
- [x] Tests: a confirmation answered twice is refused the second time
- [x] `npm run check` passes

## Phase 2: The Copilot's graph and its tools

Why: this is the Copilot itself, the loop, its tools and the pause before paying, built and tested with a stub model before it's served anywhere.

- **The connection** (`agent/copilot_client.py`): an httpx client to `UNDERCOVER_API` with `Authorization: Bearer <the handler's sign-in>` and never `X-API-Key`, whatever the environment holds.
- **The context** (`CopilotContext`, the graph's `context_schema`): the sign-in, the handler (id, first name, name, whether they can sign off over the limit), the conversation, the turn, the route and the memory store.
  - The tools read it through `ToolRuntime[CopilotContext]`, and the nodes through `Runtime[CopilotContext]`.
  - It's passed with each `invoke` and never saved. The config holds only the thread, which is the conversation's id.
- **The tools** (`agent/copilot_tools.py`), each calling the app with the handler's sign-in, and each with a kind for its card:
  - Claims:
    - `list_claims`: the queue, with each claim's status.
    - `get_claim(claim_id)`: the claim in full, with its decision, payout and any decision sent back with its note.
    - `get_claim_steps(claim_id)`: the agent's steps, trimmed.
  - Customers and policies: `get_policy`, `get_customer` and `find_customers`.
  - The agent's work:
    - `get_latest_dispatch`.
    - `list_evaluations`.
    - `get_evaluation(run_id)`: its measures only.
    - `get_settings`.
  - The context layer: the seven lookups, through `MultiServerMCPClient` on the claim agent's route (above). On the Gateway, a card shows the tool's own name.
  - Actions:
    - `start_dispatch(agents)`, with the settings' agents at once when not given.
    - `start_evaluation(labelled_set, tiny, agents)`.
    - `send_back(claim_id, note)`.
    - `sign_off_claim(claim_id)`.
    - Each start answers with the run's id.
  - **Who may act:**
    - `send_back` and `sign_off_claim` refuse in code, with the reason, for a handler who can't sign off over the limit. The Copilot tells them so, and makes no call.
    - The app still checks every action, and any refusal from the app reaches the model as "Refused (409): …", which the Copilot passes on.
- **The graph** (`agent/copilot_graph.py`), a `StateGraph` with a `PostgresSaver` from `agent/checkpoints.py` on the conversation's thread, `durability="sync"`:
  - **State:** the messages, this turn's model calls and cost, and the confirmation waiting.
  - **`start`:** begins a turn. It answers any tool call that a stopped or failed turn left unanswered with "This step stopped partway", so the history stays valid, and resets the turn's count.
  - **`recall`:** searches the handler's memory for what bears on the message, records a memory card with what it found, and gives the model what it found. With memory off it does nothing and records no card.
  - **`model`:** GPT-6 Luna at low effort, or `MODEL_NAME`. It records each reply's cost from OpenRouter's usage, and stops at 25 model calls with a short answer saying so.
  - **`tools`:** LangGraph's `ToolNode`, with a `wrap_tool_call` that records each card as working, then done, refused or failed with its time.
  - **`confirm`:** its first line is `interrupt(card)`. On a resume with `{"confirmed": true}` it signs off through the app as the handler, records an action card, and tells the model it's paid. With `false` it tells the model the handler pressed Cancel and nothing was signed off. Either way, the model goes on to answer.
  - **`remember`:** after the answer, saves the handler's message and the answer to the handler's memory (actor: the handler's id; session: the conversation). It saves nothing else.
  - **The edges:** `START → start → recall → model`; `model → tools` when it calls tools, otherwise `→ remember → END`; `tools → confirm` when a confirmation waits, otherwise `→ model`; `confirm → model`.
  - The card's claim, customer, amount and reason come from the app's records, never from what the model wrote.
- **Memory** (`agent/memory.py`):
  - `for_copilot()` gives `AgentCoreMemoryStore` when `UNDERCOVER_COPILOT_MEMORY_ID` is set.
  - `recall(store, handler_id, query)` searches only under `("handlers", handler_id)`.
  - `save_turn(store, handler_id, conversation_id, message, answer)` saves two events.
  - A store that can't be reached only logs a warning, and the turn goes on.
- **The model** (`agent/model.py`): `copilot_model()` gives `openai/gpt-6-luna` at `low`, or `MODEL_NAME` with no effort.
- **The instructions** (`agent/copilot.md`), written as goals:
  - who it works for;
  - what it can see and do, and what it can't do yet and where on the dashboard to do it;
  - what needs a handler after a dispatch;
  - the three success criteria;
  - how to answer: briefly, in plain business English and US dollars, with every figure from a tool.
  - They don't script its steps.

Done when (tests with a stub model, the app on SQLite, the context layer in the test process and a stand-in store):

- [x] The loop: a lookup, then an answer; each tool call is a card that goes from working to done with its time, and a context-layer card names its file and owner
- [x] A refusal from the app reaches the model and its card shows refused with the reason
- [x] Marcus asking to sign off or send back is refused in code with the reason, and no call reaches the app
- [x] The pause: `sign_off_claim` pauses with a card read from the records, even when the model's message names a different amount; a Copilot built afresh on the same saved state resumes with `{"confirmed": true}`, signs off as the handler and pays once, and no tool before the pause runs again
- [x] Cancel: resuming with `{"confirmed": false}` pays nothing, and the model is told the handler cancelled
- [x] The sign-in is in no checkpoint, config, step or memory event (each searched for the token's text), and no request carries `X-API-Key` with `UNDERCOVER_API_KEY` set
- [x] At 25 model calls the turn ends with a short answer saying so
- [x] A turn after one that stopped mid-step starts cleanly: its unanswered tool call is answered and the model is called with a valid history
- [x] Memory: the lookup searches only the handler's namespace and records a card with what it found; after the turn exactly two events are saved, the message and the answer; with memory off there's no card and no save
- [x] On the Gateway (the stand-in Gateway), only the context layer's seven tools are loaded, and cards show their own names
- [x] `npm run check` passes

## Phase 3: Waiting for the work, and the success criteria

Why: "work the queue and tell me what needs me" and "are we meeting the success criteria?" both need the Copilot to wait in code for work it started, and the second needs figures worked out in code, never by the model.

- **`wait_for_work(run_id)`:** polls `GET /api/runs/{id}` (a read a handler may use) every 5 seconds, with no model calls, until the run isn't running.
  - After 15 minutes it stops, saying the work is still going and that the queue page or the Scoreboard shows it.
  - Its card shows working with the seconds so far.
  - For a dispatch it answers with the summary, and with what needs a handler: the payouts held for sign-off, the claims referred or left for a handler, and any claim sent back that the agent hasn't worked.
- **`check_success_criteria()`:**
  - Starts an evaluation of the whole held-out set with the settings' agents at once, and waits for it as above.
  - Then reads its measures, the settings and `count_payouts_over_limit`, and works out in code each criterion's target, figure and whether it's met, plus whether all three are.
  - If the evaluation fails, stops or is still going, or the app refuses to start it, the first two have no figures and say why, and the third is still reported.
  - With none paid over the limit, the third is met "because no claim has been paid over the limit yet".
  - It returns a small table ready for the answer, which the model writes around.
- **The three criteria** are added to `docs/SPEC.md`:
  - at least 70% straight through on the whole held-out set;
  - accuracy at or above the accuracy objective in Settings on the whole held-out set;
  - every payout over the limit signed off by a person.

Done when (tests with a stub model and a fake clock):

- [x] Starting a dispatch gives the run's id, and `wait_for_work` waits on that run without calling the model, then answers with what needs a handler
- [x] A start the app refuses ("Dispatch 1 is running") is passed on with the reason
- [x] After 15 minutes (fake clock) the wait ends, saying the work is still going and where to follow it
- [x] The success criteria from an evaluation's measures, the accuracy objective in Settings and the app's count: with none paid over the limit (met, and why), with one paid over the limit without a sign-off (not met), and with an evaluation that failed (no figures for the first two, the third still reported)
- [x] The figures in the tool's answer match the records exactly, and the stub model's answer is built around them
- [x] `docs/SPEC.md` lists the three criteria
- [x] `npm run check` passes

## Phase 4: The Copilot as an AgentCore app, on the laptop and ready for Runtime

Why: the app needs something to send each turn to, which answers at once and works on while the session stays busy. This is the same pattern as the claim agent's app, so it's built the same way.

- **`agent/copilot_app.py`:** `BedrockAgentCoreApp` with one entrypoint and a pydantic model for each operation:
  - `health`;
  - `turn` (`conversation_id`, `turn_id`, `message`, `token`);
  - `answer` (`conversation_id`, `turn_id`, `confirmed`, `token`).
  - A payload that's wrong gets a 400 saying what's wrong, with the token left out of the message.
  - Each turn and answer first asks the app `GET /api/me` with the sign-in. If the app doesn't accept it, the request ends there with the reason, before any model call. Otherwise it answers `{"accepted": true}` and works on a thread of its own as an async task, so `/ping` says `HealthyBusy`.
  - When the graph ends, it tells the app: `finish` with the answer, model calls and cost, or `pause` with the card. On an error, `fail` with a short reason.
  - Nothing is logged with the payload.
- **Getting ready** (`agent/ready.py`):
  - `get_ready` takes the credentials to fetch. The claim agent fetches all three. The Copilot fetches only `OPENROUTER_API_KEY` and `DATABASE_URL`, and doesn't need `UNDERCOVER_API_KEY`.
  - Nothing happens at import.
  - Off Runtime the Copilot asks for no key, since every call it makes carries the handler's sign-in, which the app checks.
- **`runtime/copilot.py`:** the file Runtime starts for the Copilot; it imports the app and runs it.
- **The platform team's project** (only what this needs):
  - `agentcore/agentcore.json` gets a second runtime, `copilot`, with entrypoint `copilot.py`, from the same `runtime` code, on the same settings as `agent`, with `additionalPolicies: ["copilot_policy.json"]`.
  - `runtime/copilot_policy.json` may call the Gateway and use `undercover_copilot_memory-*`.
  - `agentcore/cdk/lib/cdk-stack.ts` adds `UNDERCOVER_COPILOT_MEMORY_ID` to the settings it reads from `.env.local`. Both runtimes are already on V2 and built from one package.
- **`package.json`:**
  - `npm run dev` adds `dev:copilot`, `uvicorn agent.copilot_app:app --host 127.0.0.1 --port 8081 --reload --reload-dir agent`, with `.env`.
  - `check:runtime` imports both `runtime.main` and `runtime.copilot` with only the `runtime` group, which gains `langchain-mcp-adapters`.

Done when:

- [x] Tests through Starlette's `TestClient`: `health` answers `{"healthy": true}`; a wrong payload gets a 400 that doesn't contain the token; `turn` answers at once and `/ping` says `HealthyBusy` until the turn ends, then `Healthy`
- [x] Tests: a sign-in the app doesn't accept ends the turn with the reason and no model call
- [x] Tests: a turn that fails tells the app why, and the next message works; a turn that pauses tells the app the card, and an `answer` resumes it on a freshly built graph
- [x] Tests: on Runtime (an `AGENTCORE_CREDENTIAL_*_NAME` set, Identity stubbed) the Copilot fetches only `OPENROUTER_API_KEY` and `DATABASE_URL`, never `UNDERCOVER_API_KEY`
- [x] `npm run check:runtime` imports `runtime.main` and `runtime.copilot` with only the `runtime` group installed
- [x] `uv run --isolated --no-dev --only-group runtime python -m runtime.copilot` serves the health check on port 8080: `{"healthy": true}`
- [x] `npm run dev` starts the Copilot on 127.0.0.1:8081 beside the rest, and a message posted to the app as Dana reaches it and is answered (checked live in phase 6)
- [ ] **Skipped (no AWS):** `agentcore deploy` of both runtimes and a health check on `undercover_default_copilot`. That's the deployment notebook's job.
- [x] `npm run check` passes

## Phase 5: The sidebar

Why: this is what the handlers see. It needs to feel polished, keep the page beside it usable, and show each step as it happens.

- **Layout** (`dashboard/src/Copilot.tsx`, its cards in `dashboard/src/CopilotCards.tsx`, and `dashboard/src/conversations.ts` for its types and API calls; `copilot.ts` would clash with `Copilot.tsx` on Windows):
  - A sidebar on the right of every signed-in page, open the first time.
  - It collapses to a slim tab with an icon of its own, and the browser remembers the choice.
  - The page beside it stays fully usable.
  - Under 900px wide, it opens over the page instead of beside it.
  - The live view keeps its full screen, with the tab only.
- **The conversation:**
  - The handler's messages on the right, the Copilot's answers on the left.
  - Answers are markdown, shown formatted with `react-markdown` and `remark-gfm` (for small tables), with claim ids turned into links to the claim's page.
  - Under each answer, small print gives the model calls, cost and time.
  - A failed turn shows a short message saying what went wrong, and a stopped one says it stopped.
- **The cards:**
  - Each card has an icon for its kind (claims, customers and policies, the context layer, the agent's work, memory, an action), the tool's name and main input, such as `get_claim CLM-1012`, and its state: working with a spinner and the seconds so far, done with the time it took, or refused or failed with the reason.
  - Cards arrive with a short, subtle fade.
  - Clicking one opens what was asked and what came back, trimmed, with a context-layer answer's file and owner.
  - Action cards stand out in Burnished Gold.
  - A small working indicator shows below the last step while a turn works.
- **The confirmation card:** the claim, the customer, the amount it will pay and the agent's reason, with "Sign off and pay" and "Cancel". While it waits, the message box says "Answer the confirmation first". It's there after a reload, since the app keeps it.
- **Around the conversation:**
  - At the top: "New conversation", and the handler's earlier conversations, newest first, each titled with its first question.
  - An empty conversation greets the handler by first name, with a few suggested questions to click.
  - At the foot: "Ask the Copilot", where Enter sends and Shift+Enter starts a new line, disabled while a turn works, and "Signed in as" with the handler's name.
- **Polling:** the sidebar reads the conversation about once a second while a turn works or an answer is on its way, and not while it's idle. When a turn changes something, the page behind refreshes as it already does.
- **The sign-in:** `dashboard/src/auth.ts` gains `freshToken()`, which renews the session when it has less than 20 minutes left. The sidebar uses it before each message and each answer to a confirmation.
- **The brand:** Instrument Sans, JetBrains Mono for ids and figures, and gold surfaces from `docs/BRAND.md`, in light and dark.
- **End-to-end:**
  - A stand-in Copilot (`e2e/copilot-standin.ts`, port 8007) plays a scripted turn through the app with the handler's sign-in: a lookup card, an action card, a refusal card, a confirmation, and a formatted answer with a table and a claim link.
  - The backend in the end-to-end run reaches it at `UNDERCOVER_COPILOT`.

Done when:

- [x] Vitest: messages left and right; markdown with a table; claim ids as links; each card's icon, name, input and states with timings; a card opens to its detail; the confirmation card's buttons send `true` and `false`; the box disabled while working and asking for the confirmation while one waits; the greeting by first name with suggestions; the conversation list newest first; collapse remembered; `freshToken` renews under 20 minutes and not over
- [x] Playwright with the stand-in Copilot: a question shows the lookup, action and refusal cards as they arrive, then the formatted answer; the confirmation card's "Sign off and pay" carries the turn on, and "Cancel" too; after a reload the waiting card is still there; a new conversation and an earlier one from the list both open
- [x] Every existing end-to-end test passes with the sidebar open
- [x] On a narrow window (390px) the sidebar opens over the page and closes to its tab
- [x] `npm run check` passes

## Phase 6: The live checks and the handover

Why: the brief's handover conversation, on the real model, checked against our records. This is done last, after one reseed.

- `npm run seed` once, then `npm run dev` on the default model, the direct route and memory off.
- The handover conversation, as Dana Whitfield, in one conversation in the browser:
  1. "Work the queue with 10 agents and tell me what needs me."
  2. "Why does CLM-... need me?", about a payout held for sign-off.
  3. "Send it back with a note", asking the agent to look again at something in it.
  4. "Sign off on another one."
  5. "Are we meeting the success criteria we agreed?"
- Then restart `npm run dev` and pick the same conversation up.
- Sign in as Marcus Oyelaran and ask to sign off.
- Check the sidebar in light and dark mode.
- Update `docs/SPEC.md`, `docs/TECH_STACK.md` (the Copilot's part, its app, the line to it, its settings, and the Deployment section's runtime and Memory), `docs/CODE_STANDARDS.md` (the Copilot as a part of its own: it reaches the app only through `agent/copilot_client.py` with the handler's sign-in, the app reaches it only through `backend/copilot_service.py`, and its operations only through `agent/copilot_app.py`), `docs/PROCESS.md` (`npm run dev` and the stand-in Copilot) and `docs/STATUS.md`.

Done when:

- [x] Before `npm run dev`: `runtime/copilot.py` serves the health check with only the `runtime` group installed (`{"healthy": true}`)
- [x] Question 1: a dispatch of 10 starts as Dana, the Copilot waits for it in code while the queue moves beside the sidebar, and it answers with the payouts held for sign-off and anything referred or left for a handler, each matching the queue
- [x] Question 2: the answer explains the hold from the claim, its steps and the context layer, with cards for each (asked again after the instructions were made clearer: the first answer used the claim alone)
- [x] Question 3: the claim is sent back with Dana's note; the claim page shows the note "Sent back by Dana Whitfield", and the agent decides it again
- [x] Question 4 (asked again after the instructions were made clearer: the first answer asked which claim): the confirmation card shows another held claim, its customer, amount and reason, matching the claim's page; "Sign off and pay" pays it, and the claim page shows it paid and signed off by Dana Whitfield
- [x] Question 5: an evaluation of the whole held-out set runs, and every figure in the table matches the Scoreboard (straight through and accuracy), Settings (the accuracy objective) and the claims' pages (payouts over the limit and their sign-offs)
- [x] After restarting `npm run dev`, the conversation opens from the list with all its turns and cards, and a sixth question is answered with the earlier ones in mind
- [x] As Marcus Oyelaran, asking to sign off is declined with the reason and no card
- [x] The sidebar checked in light and dark mode through the Playwright MCP server, or Playwright's library if the server doesn't connect, saying so
- [x] The spend of the live checks reported, from the recorded usage and the turns' costs
- [ ] **Skipped (no AWS):** the memory on the deployed product. That's the deployment notebook's job: it tells the Copilot a preference, starts a new conversation and sees it remembered.
- [x] `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/CODE_STANDARDS.md`, `docs/PROCESS.md` and `docs/STATUS.md` describe the product as it now is
- [x] `npm run check` passes with `.env` moved out of the way
