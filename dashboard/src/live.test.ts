import { expect, it } from "vitest";
import { board, outcomeOf, tally } from "./live";
import { runClaim, runRecord } from "./testing";

it("names the outcome of each kind of ending", () => {
  expect(outcomeOf(runClaim({ status: "waiting" }))).toBeNull();
  expect(outcomeOf(runClaim({ status: "awaiting_sign_off" }))).toBe("sign_off");
  expect(outcomeOf(runClaim({ status: "needs_handler" }))).toBe("handler");
  expect(
    outcomeOf(runClaim({ status: "decided", decision: "refer", payout: 0 })),
  ).toBe("refer");
});

it("waits for the payment before stamping an approval", () => {
  const approved = { decision: "approve" as const, payout: 420 };
  expect(
    outcomeOf(runClaim({ status: "in_progress", ...approved })),
  ).toBeNull();
  expect(outcomeOf(runClaim({ status: "decided", ...approved }))).toBe(
    "approve",
  );
});

it("puts the claims at work first and the waiting last, each in the dispatch's order", () => {
  const run = runRecord({
    claims: [
      runClaim({ claim_id: "A", status: "waiting" }),
      runClaim({ claim_id: "B", status: "decided", decision: "refer" }),
      runClaim({ claim_id: "C", status: "in_progress" }),
      runClaim({ claim_id: "D", status: "needs_handler" }),
      runClaim({ claim_id: "E", status: "in_progress" }),
    ],
  });
  expect(board(run).map((claim) => claim.claim_id)).toEqual([
    "C",
    "E",
    "B",
    "D",
    "A",
  ]);
});

it("counts payouts waiting for sign-off apart from those paid", () => {
  const numbers = tally(
    runRecord({
      claims: [
        runClaim({ status: "decided", decision: "approve", payout: 420 }),
        runClaim({ status: "decided", decision: "approve", payout: 80 }),
        runClaim({
          status: "awaiting_sign_off",
          decision: "approve",
          payout: 2240,
        }),
        runClaim({ status: "in_progress" }),
        runClaim({ status: "waiting" }),
      ],
    }),
  );
  expect(numbers.counts.approve).toBe(2);
  expect(numbers.counts.sign_off).toBe(1);
  expect(numbers.paid).toBe(500);
  expect(numbers.awaiting).toBe(2240);
  expect(numbers.done).toBe(3);
  expect(numbers.working).toBe(1);
});
