import type { APIRequestContext } from "@playwright/test";
import { expect } from "@playwright/test";

/** Start a claim on a thread, the way the agent does. */
export function start(request: APIRequestContext, claimId: string) {
  return request.post(`/api/claims/${claimId}/start`, {
    data: { thread_id: `${claimId}-e2e` },
  });
}

/** Start a claim and record a decision, the way the agent does. */
export async function decide(
  request: APIRequestContext,
  claimId: string,
  decision: "approve" | "decline" | "refer",
  payout: number,
) {
  expect((await start(request, claimId)).ok()).toBe(true);
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

/** Open a queue run without starting the agent, so the test can play its part. */
export async function openRun(
  request: APIRequestContext,
  cap: number,
): Promise<number> {
  const response = await request.post("/api/runs/open", { data: { cap } });
  expect(response.ok()).toBe(true);
  return ((await response.json()) as { run_id: number }).run_id;
}

/** Record a payment, as the agent's graph does after a decision. */
export async function pay(
  request: APIRequestContext,
  claimId: string,
  amount: number,
) {
  const response = await request.post(`/api/claims/${claimId}/payment`, {
    data: { amount },
  });
  expect(response.ok()).toBe(true);
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
