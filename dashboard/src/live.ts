import type { Run, RunClaim } from "./api";

export type LiveOutcome =
  "approve" | "decline" | "refer" | "sign_off" | "handler";

export const LIVE_OUTCOMES: Record<LiveOutcome, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
  sign_off: "Waiting for sign-off",
  handler: "Left for a handler",
};

/** A card's stamp, once its claim has ended. An approval is stamped once it's paid. */
export function outcomeOf(claim: RunClaim): LiveOutcome | null {
  if (claim.status === "awaiting_sign_off") return "sign_off";
  if (claim.status === "needs_handler") return "handler";
  return claim.status === "decided" ? claim.decision : null;
}

/** Whether a claim of a run has reached an end: decided, held or left for a handler.
 * A claim sent back waits for the agent again. */
export function hasEnded(status: string): boolean {
  return !["waiting", "in_progress", "sent_back"].includes(status);
}

/** Where a card goes on the board: those being worked at the front, the waiting last. */
function place(claim: RunClaim): number {
  if (claim.status === "in_progress") return 0;
  return outcomeOf(claim) ? 1 : 2;
}

/** The dispatch's claims in the board's order, each group in the dispatch's order. */
export function board(run: Run): RunClaim[] {
  return run.claims.toSorted((a, b) => place(a) - place(b));
}

export interface Tally {
  counts: Record<LiveOutcome, number>;
  done: number;
  working: number;
  paid: number;
  awaiting: number;
}

/** The dispatch's numbers: its outcomes so far, and the payouts paid and held. */
export function tally(run: Run): Tally {
  const counts: Record<LiveOutcome, number> = {
    approve: 0,
    decline: 0,
    refer: 0,
    sign_off: 0,
    handler: 0,
  };
  let paid = 0;
  let awaiting = 0;
  for (const claim of run.claims) {
    const outcome = outcomeOf(claim);
    if (outcome) counts[outcome] += 1;
    if (outcome === "approve") paid += claim.payout ?? 0;
    if (outcome === "sign_off") awaiting += claim.payout ?? 0;
  }
  const done = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const working = run.claims.filter(
    (claim) => claim.status === "in_progress",
  ).length;
  return { counts, done, working, paid, awaiting };
}
