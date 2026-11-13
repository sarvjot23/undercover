import type { APIRequestContext } from "@playwright/test";
import { expect } from "@playwright/test";

/** The agent's API key for the end-to-end backend. Each spec's `request` sends it. */
export const AGENT_KEY = "e2e-agent-key-0123456789abcdefghijklmnop";

/** Start a claim on a thread, the way the agent does. */
export function start(request: APIRequestContext, claimId: string) {
  return request.post(`/api/claims/${claimId}/start`, {
    data: { thread_id: `${claimId}-e2e` },
  });
}

type Choice = "approve" | "decline" | "refer";

/** The reasons every decision recorded by these tests gives. */
export const REASONS =
  "Recorded by the end-to-end test. The wording settles it.";

/** Work out a payout of this amount, so an approval has its calculation on file:
 * one expense under emergency medical for the payout plus the plan's deductible. */
async function calculate(
  request: APIRequestContext,
  claimId: string,
  payout: number,
) {
  const claim = (await (
    await request.get(`/api/claims/${claimId}`)
  ).json()) as {
    plan: { deductible: number };
  };
  const response = await request.post(`/api/claims/${claimId}/payout`, {
    data: {
      benefit: "emergency_medical",
      lines: [
        {
          description: "Covered costs",
          amount: payout + claim.plan.deductible,
          quantity: 1,
          kind: "expense",
          nights: 0,
          hours: 0,
        },
      ],
      paid_by_others: 0,
    },
  });
  expect(((await response.json()) as { payout: number }).payout).toBe(payout);
}

/** Record a decision on a claim in progress, the way the agent does. */
export async function record(
  request: APIRequestContext,
  claimId: string,
  decision: Choice,
  payout: number,
) {
  if (decision === "approve") await calculate(request, claimId, payout);
  const response = await request.post(`/api/claims/${claimId}/decision`, {
    data: {
      decision,
      payout,
      reasons: REASONS,
      policy_section: "3. Trip Delay",
      decided_by: "UnderCover Agent, version 1",
    },
  });
  expect(response.ok()).toBe(true);
}

/** Start a claim and record a decision, the way the agent does. */
export async function decide(
  request: APIRequestContext,
  claimId: string,
  decision: Choice,
  payout: number,
) {
  expect((await start(request, claimId)).ok()).toBe(true);
  await record(request, claimId, decision, payout);
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
      version: null,
      round_id: null,
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
