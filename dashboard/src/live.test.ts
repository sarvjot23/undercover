import { expect, it } from "vitest";
import type { ClaimSummary } from "./api";
import type { LiveState } from "./live";
import { outcomeOf, progress, reduce, START, tally } from "./live";
import { summary } from "./testing";

function poll(state: LiveState, claims: ClaimSummary[], running = true) {
  return reduce(state, { type: "poll", claims, running });
}

const second = summary({ claim_id: "CLM-1002" });
const waiting = [summary(), second];

it("names the outcome of each kind of decision", () => {
  const approved = { decision: "approve" as const, payout: 420 };
  expect(outcomeOf(summary({ status: "decided", ...approved }))).toBe(
    "approve",
  );
  expect(outcomeOf(summary({ status: "awaiting_sign_off", ...approved }))).toBe(
    "sign_off",
  );
  expect(
    outcomeOf(summary({ status: "decided", decision: "decline", payout: 0 })),
  ).toBe("decline");
  expect(
    outcomeOf(summary({ status: "decided", decision: "refer", payout: 0 })),
  ).toBe("refer");
  expect(outcomeOf(summary({ status: "in_progress" }))).toBeNull();
});

it("follows a claim from in progress to its stamp, then moves on", () => {
  let state = poll(START, waiting);
  expect(state.focus).toBeNull();

  state = poll(state, [summary({ status: "in_progress" }), second]);
  expect(state).toMatchObject({ focus: "CLM-1001", stage: "working" });
  expect(progress(state)).toEqual({ position: 1, total: 2 });

  const decided = summary({
    status: "decided",
    decision: "decline",
    payout: 0,
  });
  state = poll(state, [decided, second]);
  expect(state).toMatchObject({ stage: "stamped", finished: ["CLM-1001"] });
  expect(progress(state)).toEqual({ position: 1, total: 2 });

  state = reduce(state, { type: "held" });
  expect(state.stage).toBe("stamped");

  const next = summary({ claim_id: "CLM-1002", status: "in_progress" });
  state = poll(state, [decided, next]);
  expect(state.stage).toBe("leaving");

  state = reduce(state, { type: "left" });
  expect(state).toMatchObject({ focus: "CLM-1002", stage: "working" });
  expect(progress(state)).toEqual({ position: 2, total: 2 });
});

it("leaves the last stamp once the queue run has ended", () => {
  let state = poll(START, [summary({ status: "in_progress" })]);
  const approved = summary({
    status: "decided",
    decision: "approve",
    payout: 420,
  });
  state = poll(state, [approved]);
  state = reduce(state, { type: "held" });
  expect(state.stage).toBe("stamped");
  state = poll(state, [approved], false);
  expect(state.stage).toBe("leaving");
  state = reduce(state, { type: "left" });
  expect(state.focus).toBeNull();
  expect(tally(state)).toEqual({
    counts: { approve: 1, decline: 0, refer: 0, sign_off: 0 },
    paid: 420,
    awaiting: 0,
  });
});

it("drops a claim whose run failed", () => {
  let state = poll(START, [summary({ status: "in_progress" })]);
  state = poll(state, [summary()]);
  expect(state.focus).toBeNull();
  expect(state.finished).toEqual([]);
});

it("counts payouts waiting for sign-off apart from those paid", () => {
  const state: LiveState = {
    ...START,
    finished: ["CLM-1001", "CLM-1002"],
    claims: [
      summary({ status: "decided", decision: "approve", payout: 100 }),
      summary({
        claim_id: "CLM-1002",
        status: "awaiting_sign_off",
        decision: "approve",
        payout: 1200,
      }),
      summary({
        claim_id: "CLM-1003",
        status: "decided",
        decision: "approve",
        payout: 999,
      }),
    ],
  };
  expect(tally(state)).toMatchObject({ paid: 100, awaiting: 1200 });
});
