# Plan: sending claims back, and the agent as an AgentCore app

The plan for `docs/RUNTIME.md`, in five phases: the brief's four steps in order, one phase each, then the live checks and the handover. Each phase ends with its boxes ticked here, `docs/STATUS.md` updated and a commit of its own.

**The brief's sidenote, as it asks:** for consistency with the course, read `labs/week3day4_lab2.ipynb`, which deploys the agent on AgentCore Runtime and points the app at it, without running it. Where the notebook and the brief differ, follow the brief. The pause in step 1 was in the course's build for self-improvement, before the security build took it out: `git show week2day5-end:agent/harness.py` has its `wait_for_sign_off` node, and `git show week2day5-end:agent/service.py` its `resume_claim` route. Lab 1's `agentcore dev` also serves on port 8080, so stop it before `npm run dev`.

**Built locally, with no AWS.** As agreed for the last three builds, nothing here is deployed. The agent runs as an AgentCore app on 127.0.0.1:8080, and the Runtime route (`UNDERCOVER_AGENT_RUNTIME`), the credentials from AgentCore Identity and `agentcore deploy` are built and tested with stand-ins only. Any check that needs AWS is marked **Skipped (no AWS)** below rather than left out. Filling in the settings later turns them on with no rebuild.

## Where this build starts from

Our build differs from the brief's notes in a few places, and the plan follows the brief's intent:

- **The pause is still here.** Our security build kept it: the claim graph's `sign_off` node waits with `interrupt()`, and the service's `resume_claim` closes the paused work after a sign-off. Step 1 is mostly about moving memory after the pause, not pausing an evaluation's copy, and reading the answer from the app.
- **Where things are:** the claim graph is `agent/graph.py` and `agent/claim.py` (not `agent/harness.py`); the app's claim routes are `backend/routes/claims.py`, its tables `backend/db.py`, the run routes `backend/routes/runs.py` and `backend/runs.py`, the rounds `backend/routes/rounds.py` and `backend/rounds.py`; the sign-off panel is `SignOff` inside `dashboard/src/ClaimView.tsx`; the agent's service is `agent/service.py`, called through `backend/agent_service.py`.
- **A claim is held with a lease** (`agent/lease.py`, `backend/leases.py`): a worker takes it, renews it every 5 seconds and it runs out after 20. A resumed claim holds its lease the same way, which does what step 2 asks of "tells the app every minute ... heard from in the last five minutes", with a shorter window. A dispatch already leaves alone a claim whose lease another worker holds. Runs and rounds have no lease, so step 4 gives them the word every minute that the brief describes.
- **A proposal has no id of its own:** it waits on its round, and a handler's review becomes a row in `round_events`. The `proposal_id` in `carry_round_on` is that review's `event_id`.

**Something in the platform team's files that the agent needs:** their deployment gives the agent the app's address as `UNDERCOVER_API`, but our agent has the address fixed at `http://127.0.0.1:8000` (`agent/client.py`). Phase 3 makes the agent read `UNDERCOVER_API`, with that address as its default. Nothing in `agentcore/` or `runtime/` changes.

## Phase 1: The claim approval comes back

Why: the pause and the resume exist, but memory is saved before the pause (so a claim is remembered even if the agent never hears about the sign-off), an evaluation's copy pauses and has its thread deleted afterwards, and the answer comes from the claim's record only by chance. This phase makes the pause match step 1 so step 2 can add the send back.

- `agent/graph.py`:
  - After the decision, an approval waiting for sign-off goes to `sign_off`, which pauses. A payment the Gateway refused goes there too, as now. An evaluation's copy never goes to `sign_off`: its work ends, as it does today.
  - `remember` moves after the pause: a sign-off resumes into `remember`, then `close`. A new `remembered` flag in the graph's state stops it saving twice, as when a payment the Gateway refused was remembered before `pay` held it.
  - `sign_off` stays a node with nothing before its `interrupt()`, since LangGraph runs it again from the top on a resume. The answer it gets is `{"signed_off_by": ...}` (phase 2 adds the send back).
- `agent/claim.py`:
  - `paused(claim_id)` tells whether a claim's thread has an interrupt waiting (`graph.get_state(config).interrupts`).
  - `resume(claim_id)` reads the answer from the app's record (the sign-off) and resumes the thread with `Command(resume=...)`, `durability="sync"`, holding the claim's lease.
  - `work()` no longer deletes an evaluation copy's thread, since a copy doesn't pause.
- `agent/service.py`: `resume_claim` refuses a claim that isn't paused with a 409 that says why, answers at once and works in the background, outside any run, on the claim agents of the current version, beside anything else. The start-up that closed signed-off claims goes (step 3 says nothing happens as the agent starts); a sign-off the agent never heard about is a known gap.
- `backend/routes/claims.py`: the sign-off still moves the claim only while it's waiting for sign-off, records who signed off and pays, commits, then asks the agent to resume the claim. It answers with the updated claim whatever happens to that call, and logs a warning when the call fails or times out.
- `docs/STATUS.md` lists the gap: a sign-off the agent never received leaves the agent's work paused and the claim not saved to memory.

Done when:

- [x] Tests with a stub model: an approval over the limit pauses with its place saved, and `paused` says so
- [x] A payment the Gateway refused (the stand-in Gateway) pauses, and its claim is remembered once only
- [x] An evaluation's copy over the limit doesn't pause and has no interrupt waiting
- [x] A resume after a sign-off ends the work, pays nothing and saves the claim to a stand-in memory
- [x] `resume_claim` refuses a claim that isn't paused, with the reason
- [x] The sign-off answers with the updated claim when the agent can't be reached, and logs a warning
- [x] `npm run check` passes
- [x] (Checked live in phase 5, as the brief asks) With `npm run dev` running, a claim over the limit pauses, and signing it off on the dashboard pays it and ends the agent's work (its last step is the agent's closing line)

## Phase 2: Sign off or send back

Why: a handler who thinks the payout is wrong needs a way to tell the agent. The decision sent back is kept, not overwritten, so the claim's history stays complete.

- **The records** (`backend/db.py`): a new claim status, `sent_back`. A new table, `sent_back_decisions`, holds each decision that was sent back: the whole decision record, the note, who sent it back and when. A claim can be sent back more than once, so it has a row for each.
- **The send back** (`POST /api/claims/{id}/send-back`, `send_back_claim`): the signed-in handler with the same check as the sign-off; a note from 1 to 1,000 characters. It refuses an evaluation's copy and a claim that isn't waiting for sign-off with a 409, using the same conditional move as the sign-off, so a sign-off and a send back at the same moment can't both go through. In one transaction it keeps the decision with the note, clears the current decision and the claim's calculations (so a new approval needs a new calculation), records the note as a `send_back` step and moves the claim to `sent_back`. It then asks the agent to resume the claim, and answers with the updated claim whatever happens to that call, logging a warning when it fails.
- **Taking a sent-back claim** (`POST /api/claims/{id}/take`, the agent's key only): moves the claim from `sent_back` to `in_progress` and gives the caller its lease, in one conditional update, so only the first caller gets it. `resume_claim` takes the claim before it answers, and refuses with the reason when it can't. A dispatch's claims are now the ones in progress, sent back and waiting, oldest first; its claim agent takes a sent-back claim the same way and leaves it if another got there first. A dispatch already leaves alone a claim whose lease another worker holds, so it leaves a resumed claim alone while the resume works.
- **The agent decides again** (`agent/graph.py`, `agent/claim.py`): whoever takes the claim resumes its thread with the note from the app's record (the latest sent-back decision). `sign_off` then sends the graph back to the model with a message from the handler, naming who sent the decision back, with `model_calls` back to 0 and `remembered` cleared. The earlier decision is already gone from the app, so nothing can pay it. The new decision goes through the same checks: an approval needs its calculation, one over the limit waits for sign-off again, one within it is paid. If the claim's thread isn't paused (it never paused, or its saved progress is gone), the claim starts afresh with the note as its first message from the handler.
- **The message carrying the note** is written in the agent's code (`agent/claim.py`), not its instructions, so the improver can't drop it: treat it as a senior handler's review of the decision, check it against the policy wording and the claims manual like everything else, and refer the claim to a handler, giving the reason, when the wording doesn't support what the note asks. `backend/instructions/claim.md` changes only where it says a decision can't be changed.
- **The dashboard:**
  - On a claim waiting for sign-off, Dana sees Sign off and Send back. Send back opens a note field ("What should the agent look at again?"), required, up to 1,000 characters, with a count. Marcus and Priya see why they can't do either.
  - The queue shows "Sent back" with its own badge.
  - The claim page shows each decision that was sent back, with its note, who sent it back and when, beside the current decision. The note is among the steps.
  - A sent-back claim with no agent working says "Waiting for the next dispatch".
- `docs/SPEC.md` gets the send back in Working the queue and in Rules.

Phases 1 and 2 share one commit: their changes to the claim graph, `agent/claim.py` and the service were made together before phase 1 was committed.

Done when:

- [x] Tests: the send back's refusals (no note, a note over 1,000 characters, a handler who can't sign off, an evaluation's copy, a claim not waiting for sign-off)
- [x] A sign-off and a send back at the same moment: one goes through, the other gets a 409
- [x] The decision sent back is kept with its note, who and when; the current decision and calculations are cleared; the note is a step
- [x] A sent-back claim is taken once when the resume and a dispatch both ask
- [x] A dispatch started during a resume leaves its claim alone
- [x] With a stub model, the new decision is paid when it's within the limit, and waits for sign-off again when it's over
- [x] A send back the agent never received (the agent away) is worked by the next dispatch, which resumes the paused thread with the note
- [x] Vitest: the two buttons, the required note and its limit, the sent-back decisions with their notes, the queue's badge, "Waiting for the next dispatch"
- [x] An end-to-end test sends a claim back and sees it in the queue and on its page
- [x] `npm run check` passes
- [x] (Checked live in phase 5, as the brief asks) With `npm run dev` running, a claim sent back with a note is decided again by the agent, and the claim page shows both decisions and the note, checked in the browser (through the Playwright MCP server, or Playwright's library from a script if the MCP server doesn't connect, as in the last build)

## Phase 3: The agent as an AgentCore app

Why: an AgentCore app runs the same way on the laptop and on Runtime, so the agent we test locally is the one Runtime would start. Registering each piece of work as an async task is what keeps a Runtime session alive for as long as its work.

- **`agent/entrypoint.py`** (new): `app = BedrockAgentCoreApp()` with one `@app.entrypoint`, a plain `def` taking the payload and the request's `context`. Each payload names an operation and its inputs, checked with a pydantic model for each (a discriminated union on `operation`); an unknown operation or an input missing or wrong is a 400 that says what's wrong. The operations are the service's, by their operation ids: `health`, `start_dispatch`, `start_evaluation`, `start_round`, `decide_on_proposal`, `stop_round`, `work_claim` and `resume_claim`. Each answers `{"accepted": true}`, or `{"refused": "<reason>"}` where the service gave a 409; `health` answers `{"healthy": true}`.
- **Work on its own thread:** each operation checks what it must, registers the work with `app.add_async_task` before it answers, and runs it on a thread of its own that calls `app.complete_async_task` however the work ends. The AgentCore app's `/ping` then says `HealthyBusy` while anything is going.
- **Getting ready on the first request** (`agent/ready.py`, new): nothing happens on import or as the app starts. The first request, once in the process and under a lock, gets ready before it answers. On Runtime (when any `AGENTCORE_CREDENTIAL_<NAME>_NAME` is set) it reseeds Python's random numbers and fetches each credential from Identity with `requires_api_key(provider_name=...)`, applied while getting ready, into the setting `<NAME>`. Then it checks it has the agent's key and opens the checkpoint pool. A failure answers with the error and the next request tries again. The health check gets ready like any other request.
- **The key:** off Runtime, a request without `Authorization: Bearer <UNDERCOVER_API_KEY>` gets a 401, apart from the health check. On Runtime the agent asks for none, since AWS checks the caller first.
- **`agent/client.py`** reads the app's address from `UNDERCOVER_API`, `http://127.0.0.1:8000` by default (see above).
- **`agent/checkpoints.py`**: `prepare_threshold=None`, so the pool works through either of Supabase's poolers.
- **The app's two routes** (`backend/agent_service.py`): one `send(payload)` that answers accepted, refused with the reason, not taken (never sent, never connected, or an error answer) or unknown (a timeout or an answer cut off once it was sent). On the laptop route it posts to `{UNDERCOVER_AGENT}/invocations`, by default `http://127.0.0.1:8080`, with the key as a bearer token and a 10-second timeout. With `UNDERCOVER_AGENT_RUNTIME` set, it calls `invoke_agent_runtime` with boto3 in the app's region, a new session id of 33 characters or more for each request, one attempt, 5 seconds to connect and 20 to read. A refusal reaches the handler as the 409 does today, not taken as today's 503, and unknown as a 504 telling them to reload the page to see whether it went through. The sign-off and the send back answer with the updated claim whatever happens.
- **The service goes:** `agent/service.py` and its FastAPI app are replaced by the entrypoint; its tests move to `agent/tests/test_entrypoint.py` through Starlette's `TestClient`.
- **Dependencies and checks:** `bedrock-agentcore` joins the project; a `runtime` dependency group lists exactly what the agent imports on Runtime (`bedrock-agentcore` included); `boto3` joins the `server` group. `npm run check:runtime` imports `runtime.main` with only that group installed, in a temporary environment, and runs in `npm run check`. Ruff and pyright cover `runtime/`. Pytest's setup and the end-to-end backend blank `UNDERCOVER_AGENT_RUNTIME`, so no test calls AWS.
- **`npm run dev`** serves `agent.entrypoint:app` with uvicorn on 127.0.0.1:8080, with reload, in place of the service on 8002. The end-to-end stand-in for the agent answers `/invocations` and `/ping`, and Playwright waits for its `/ping`.

Done when:

- [x] Tests through `TestClient` with stand-ins for the work and for Identity: importing the agent opens nothing; on Runtime the first request fetches each credential into its setting once
- [x] Each operation accepts work and refuses it; a payload with an input missing, or an unknown operation, gets a 400 saying what's wrong
- [x] `/ping` is `HealthyBusy` while work is going, and `Healthy` once it has finished or failed
- [x] Off Runtime, a request without the key gets a 401 and the health check doesn't; on Runtime a request without it is let through
- [x] The app's laptop route with stand-ins: the key, the payload, an acceptance, a refusal passed on, a failed connection, an error answer, and a timeout or a cut-off answer that changes nothing
- [x] The app's Runtime route with a stand-in boto3 client: the session id (33 characters or more, new each time), the payload, an acceptance, a refusal, a failed connection, a `ClientError`, and a read timeout or cut-off answer that changes nothing
- [x] `npm run check` passes, with `check:runtime` among its checks
- [x] (Checked live in phase 5, with the other live checks) With `npm run dev` stopped, `uv run --env-file .env --isolated --only-group runtime python -m runtime.main` serves the agent on port 8080, and `{"operation": "health"}` posted to `/invocations` answers `{"healthy": true}`
- [x] **Skipped (no AWS):** the agent on Runtime answering through `invoke_agent_runtime`, and its credentials fetched from AgentCore Identity. Both are covered by the stand-in tests above and run once `agentcore deploy` and `UNDERCOVER_AGENT_RUNTIME` are set up

## Phase 4: The app keeps one run at a time

Why: on Runtime each dispatch has a session, a process, of its own, so the agent can no longer keep one piece of work at a time in its memory. Only the app sees them all. This is the largest phase.

- **The app starts the work itself:** `POST /api/dispatches` and `/api/evaluations` create the run, `POST /api/rounds` creates the round, and `POST /api/rounds/{id}/decision` records the review (as `rounds.decide` does today, and now keeping the whole proposal with the review so it can be undone). Each does its check and its writes in a short transaction of its own, committed before it asks the agent: it first takes a lock with a conditional update of one row in a new one-row table, `agent_work`, which holds on Postgres, on SQLite and through the transaction pooler, so two starts at the same moment can't both go through. The unique index on running runs stays as a second guard. A request uses one connection at a time.
- **One piece of work at a time:** a dispatch, an evaluation, or a round while it works (open with no proposal waiting). A second start gets a 409 naming what's going, such as "Dispatch 7 is running". Resuming a claim runs beside anything.
- **Three operations in place of four:** `{"operation": "work_run", "run_id": ...}`, `{"operation": "work_round", "round_id": ...}` and `{"operation": "carry_round_on", "round_id": ..., "proposal_id": ...}`. The agent refuses a run that isn't running and a round that isn't open. It no longer creates runs or rounds, apart from the evaluations a round makes as it goes, and no longer records reviews: `carry_round_on` reads the review and its reason from the app (`GET /api/rounds/{id}/reviews/{event_id}`, the agent's key).
- **When the agent didn't take the work**, the app undoes it: the run is stopped with the reason, a new round is stopped, and a review is undone (its version, if an approval made one, is removed, and the proposal waits again). When the answer is unknown, it changes nothing.
- **Word every minute:** while the agent works on a run or a round it tells the app so every minute (`POST /api/runs/{id}/heard`, `/api/rounds/{id}/heard`); a round's word covers its running evaluation. Runs and rounds get `heard_at`, set when the app starts the work and at each word, and `stop_reason`. When a handler next asks to start work, anything not heard from for five minutes is marked stopped with "The agent stopped answering", a round with its running evaluation, and the new work goes ahead. The app never stops a round's evaluation on its own.
- **The agent stops only its own work:** nothing is stopped when it gets ready, and when its work on a run or a round fails it stops only that one, by its id; stopping a round stops its running evaluation.
- **The dashboard** shows a run's and a round's reason for stopping.
- **The end-to-end stand-in** gets the app's address and the agent's key, and finishes each run it's given, so later starts aren't refused.

Phases 3 and 4 share one commit, as 1 and 2 do: phase 4 was started in the same files while phase 3's full check ran (it passed: 457 Python, 111 TypeScript and 24 end-to-end tests).

Done when:

- [x] Tests: a second start refused while a dispatch, an evaluation or a working round is going, with what's going named
- [x] Two starts at the same moment: one goes through
- [x] A start after the work went quiet for five minutes marks it stopped with "The agent stopped answering" (a round with its evaluation) and goes ahead
- [x] A start the agent didn't take is undone (run stopped with the reason, round stopped); a timeout leaves the work going
- [x] A review the agent didn't take is undone, and the proposal waits for a review again
- [x] A failed run stops only itself; a failed round stops itself and its running evaluation
- [x] A resume runs beside a dispatch
- [x] The end-to-end tests pass with the app creating runs, rounds and reviews
- [x] `npm run check` passes
- [x] (Checked live in phase 5) With `npm run dev` running, a dispatch at N=25 works the queue, and starting another while it runs is refused on the dashboard

## Phase 5: The live checks and the handover

After one `npm run seed`, with `npm run dev` running on the default model, on the direct route and with memory off:

- [x] A dispatch at N=25 works the queue
- [x] Signed in as Dana Whitfield: one claim over the limit sent back with a note and decided again by the agent, and another signed off
- [x] An evaluation of the evaluation set's five tiny claims
- [x] The claim pages of the sent-back and the signed-off claims checked in the browser: both decisions, the note, who sent it back and when, and the new decision
- [x] What the runs spent, from the recorded usage, reported
- [x] The agent answers its health check through `runtime/main.py` on the laptop
- [x] `npm run check` passes with `.env` moved out of the way
- [x] `docs/SPEC.md`, `docs/TECH_STACK.md` (with the agent on Runtime in its Deployment section), `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` and `docs/STATUS.md` describe the product as it now is
- [ ] **Skipped (no AWS):** Lab 2's deployment: `agentcore deploy`, the app on Lambda pointed at the runtime, and a dispatch and a send back on Runtime
- [x] Every box in this plan is ticked or marked skipped. Phases 1 and 2 share a commit, as do 3 and 4 (see the notes above); phase 5 has its own
