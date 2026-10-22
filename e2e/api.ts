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
