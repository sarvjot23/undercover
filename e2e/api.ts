import { DatabaseSync } from "node:sqlite";
import type { APIRequestContext } from "@playwright/test";
import { expect } from "@playwright/test";

/** Start a claim and record a decision, the way the agent does. */
export async function decide(
  request: APIRequestContext,
  claimId: string,
  decision: "approve" | "decline" | "refer",
  payout: number,
) {
  expect((await request.post(`/api/claims/${claimId}/start`)).ok()).toBe(true);
  const response = await request.post(`/api/claims/${claimId}/decision`, {
    data: {
      decision,
      payout,
      reasons: "Recorded by the end-to-end test. The wording settles it.",
      policy_section: "3. Trip Delay",
    },
  });
  expect(response.ok()).toBe(true);
}

/**
 * Open a queue run as POST /api/runs would, but without starting the agent,
 * so the test can play the agent's part through the API.
 */
export function openRun(cap: number): number {
  const path = process.env.UNDERCOVER_E2E_DB ?? "";
  const database = new DatabaseSync(path);
  const result = database
    .prepare(
      "INSERT INTO runs (cap, total, status, todos, started_at) VALUES (?, ?, 'running', '[]', ?)",
    )
    .run(cap, cap, new Date().toISOString());
  database.close();
  return Number(result.lastInsertRowid);
}

/** Play the agent's part on one claim of a run: take it, start it and decide it. */
export async function work(
  request: APIRequestContext,
  runId: number,
  claimId: string,
  decision: "approve" | "decline" | "refer",
  payout: number,
) {
  const taken = await request.post(
    `/api/runs/${String(runId)}/claims/${claimId}`,
  );
  expect(taken.ok()).toBe(true);
  await decide(request, claimId, decision, payout);
}

export async function writeTodos(
  request: APIRequestContext,
  runId: number,
  todos: { claim_id: string; note: string; status: string }[],
) {
  const response = await request.put(`/api/runs/${String(runId)}/todos`, {
    data: { todos },
  });
  expect(response.ok()).toBe(true);
}

export async function finishRun(
  request: APIRequestContext,
  runId: number,
  summary: string,
) {
  const response = await request.post(`/api/runs/${String(runId)}/finish`, {
    data: { summary },
  });
  expect(response.ok()).toBe(true);
}
