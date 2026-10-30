# Tech stack

- `backend/`: FastAPI and SQLAlchemy Core, so each query is written once for both databases. It uses Supabase (Postgres) when `DATABASE_URL` is in its environment, in a schema of its own, `undercover`, and otherwise SQLite. `npm run dev` passes `.env`; the tests never do. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount. Supabase's free plan allows 15 connections through the session pooler, so each process uses at most 4.
- `agent/`: our own harness on OpenRouter, with no other agent framework, in four parts:
  - The queue agent, on LangChain's `create_agent` and its middleware, works a run (one entry point that takes a run id).
  - The claim agent, a hand-written LangGraph graph, works a claim (one entry point that takes a claim id and a thread id). Its nodes record each step, return refusals to the model and stop at 30 model calls. It pays as a step of the graph, and waits for a sign-off with `interrupt()` when the backend says a claim needs one.
  - Its progress is saved after every step with LangGraph's synchronous Postgres checkpointer, in the same database, with `durability="sync"`.
  - The agent's service, a small web service and the agent's entry point, on `UNDERCOVER_AGENT` or `http://127.0.0.1:8002`. The backend calls it to start work and after each sign-off.

  Both agents reach claims, documents and their instructions only through the backend's API. They use `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, or the model in the environment variable `MODEL_NAME` if set, such as `openrouter/free`. Each claim's work is one Langfuse session, named after its thread.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from, including our settings in `company.json` (the payout approval limit). The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. In `.env`: `OPENROUTER_API_KEY`, `DATABASE_URL` (the Supabase session pooler string) and `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL`.
