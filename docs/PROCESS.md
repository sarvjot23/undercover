# Process

`uv sync` and `npm install` at the repo root install everything, including a git pre-commit hook. `npm run dev` starts the backend, the agent's AgentCore app (port 8080, with reload), the context layer (port 8006) and the dashboard, and passes the backend and the agent `.env`. `npm run seed` starts the database again from `data/` and the plans and documents in `context/`. `npm run build` builds the dashboard into `dashboard/dist`, which the backend then serves itself, as it does on Lambda; delete `dashboard/dist` to go back to the backend serving only the API.

`npm run check` runs every check:

- Python: ruff (lint and format), pyright, and pytest with 80% coverage
- `npm run check:server`: the backend imports with only the `server` dependency group, the one the Lambda package has, installed in a temporary environment
- `npm run check:context`: the context layer imports with only the `context` dependency group, the one its Lambda package has, the same way
- `npm run check:runtime`: `runtime.main`, the file AgentCore Runtime starts, imports with only the `runtime` dependency group, the one the agent's package on Runtime has, the same way
- TypeScript: ESLint, Prettier, tsc, and vitest with 80% coverage
- Playwright end-to-end tests, with stand-ins for the agent's AgentCore app on port 8003, Supabase Auth on port 8004 (it signs tokens with a key of its own) and the judge on port 8005. Every spec signs in as a handler first.

`npm run check` needs no Supabase, Langfuse, OpenRouter or AWS, and passes with `.env` moved out of the way. The agent's tests run the context layer in the test process, and stand in for the AgentCore Gateway with a small MCP server and for AgentCore Memory with a stand-in store. The tests run on SQLite, and never call a model, the judge or Supabase Auth. They set a fixed test value for `UNDERCOVER_API_KEY` (the Python tests' fixtures through `backend/tests/signing.py`, the end-to-end tests in `playwright.config.ts`), so they never need the real key.

The pre-commit hook runs the format, lint, type and unit test checks on every commit.

## Planning

When asked to plan, as in "Please plan the pilot", write the plan to `docs/PLAN.md` and write no code.

- Split the work into phases, usually 5 or 6, each building on the last.
- Give each phase detailed success criteria that you can verify yourself: tests that pass, commands and their output, API calls and their responses, and pages you check in the browser with the Playwright MCP server. Write each one as a checkbox.
- Then stop and wait until you are asked to implement the plan.

## Implementing

When asked to implement the plan, as in "Please implement the plan for the pilot", build every phase in order without stopping. For each phase:

1. Build it, with tests.
2. Check every success criterion and fix whatever fails.
3. Tick off its criteria in `docs/PLAN.md` and update `docs/STATUS.md`.
4. Commit. The pre-commit hook runs the checks; if it fails, fix the problem and commit again.

When the last phase is done, run `npm run check` and report the results.

## Rules

- Add tests with each change. Tests never call a model; use a stub model.
- For live runs with the real model, reseed first with `npm run seed`, then keep to the runs the plan names, such as a dispatch or an evaluation of the five `tiny` claims. For browser checks, sign in as a handler with `HANDLER_PASSWORD` from `.env`, and never print it.
- Outside a plan, commit each change once you have checked it.
- Run `npm run check` before you hand work over.
- Never use `git commit --no-verify`.
- Never lower a threshold, turn off a rule or exclude a file to get a green run. If a rule looks wrong, stop and ask.
- Keep `docs/STATUS.md` up to date.
- Never push.
- Don't open `data/evals/` unless you're asked to.
- Everything must work on Windows: write `package.json` scripts as `uv run` commands or `.mjs` files.
