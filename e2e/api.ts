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

/** Create a dispatch without starting the agent, so the test can play its part. */
export async function createDispatch(
  request: APIRequestContext,
  n = 3,
): Promise<number> {
  const response = await request.post("/api/runs", {
    data: {
      kind: "dispatch",
      n,
      set_name: null,
      tiny: false,
      model: "openai/gpt-6-luna",
      reasoning: "low",
    },
  });
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

/** End a run, as the agent's service does when the dispatcher is done. */
export async function endRun(
  request: APIRequestContext,
  runId: number,
  how: "finish" | "stop" = "finish",
) {
  const response = await request.post(`/api/runs/${String(runId)}/${how}`);
  expect(response.ok()).toBe(true);
}

/** What the stand-in for the agent's service has been asked. */
export async function received(
  request: APIRequestContext,
): Promise<{ path: string; body: unknown }[]> {
  const response = await request.get("http://127.0.0.1:8003/received");
  return (await response.json()) as { path: string; body: unknown }[];
}
