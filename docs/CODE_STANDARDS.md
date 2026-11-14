# Code standards

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: a short README and no emojis.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.
7. Each part of the agent reaches the backend only through its own client module. The claim agent and the dispatcher use `agent/client.py` for their bookkeeping, which never reaches the scores, the evaluations, the rounds or the handlers' decisions; the improver uses `agent/improver_client.py`, and the dispatcher only asks it whether a round may start another claim. The app reaches the agent only through `backend/agent_service.py`, and the agent's operations only through `agent/entrypoint.py`. The claim agent's tools and the payment take one route, with one module for each: `agent/gateway.py` for the AgentCore Gateway and `agent/direct.py` for the app and the context layer directly. Both offer the same `call(target, operation, arguments)`, and `agent/routes.py` chooses between them. Memory is `agent/memory.py`'s alone.
8. The Copilot is a part of its own, with the same rules: it reaches the app only through `agent/copilot_client.py`, with the handler's sign-in and never the agent's key; the app reaches it only through `backend/copilot_service.py`, and its operations only through `agent/copilot_app.py`. Its context-layer tools take the claim agent's route, and its memory is `agent/memory.py`'s.
9. The dashboard reaches Supabase only through `dashboard/src/auth.ts`.
10. An agent's instructions are written as goals: what to achieve and what it works from, not a list of steps. Data such as the improver's recipe, which may be a list of steps, is kept apart from them and placed inside.
