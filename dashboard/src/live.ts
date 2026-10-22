import type { ClaimSummary } from "./api";

export type LiveOutcome = "approve" | "decline" | "refer" | "sign_off";

export const LIVE_OUTCOMES: Record<LiveOutcome, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
  sign_off: "Waiting for sign-off",
};

export const HOLD_MS = 3000;
export const LEAVE_MS = 450;

export interface LiveState {
  claims: ClaimSummary[];
  running: boolean;
  focus: string | null;
  stage: "working" | "stamped" | "leaving";
  held: boolean;
  finished: string[];
}

export type LiveEvent =
  | { type: "poll"; claims: ClaimSummary[]; running: boolean }
  | { type: "held" }
  | { type: "left" };

export const START: LiveState = {
  claims: [],
  running: false,
  focus: null,
  stage: "working",
  held: false,
  finished: [],
};

export function outcomeOf(claim: ClaimSummary): LiveOutcome | null {
  if (claim.status === "awaiting_sign_off") return "sign_off";
  return claim.status === "decided" ? claim.decision : null;
}

/** The claim the agent is on now, other than ones already shown. */
function active(state: LiveState): ClaimSummary | undefined {
  return state.claims.find(
    (claim) =>
      claim.status === "in_progress" &&
      !state.finished.includes(claim.claim_id),
  );
}

/** Follow the claims: pick up the claim in progress, stamp it, then move on. */
function settle(state: LiveState): LiveState {
  if (state.focus === null) {
    const next = active(state);
    return next ? { ...state, focus: next.claim_id, stage: "working" } : state;
  }
  const claim = state.claims.find((c) => c.claim_id === state.focus);
  if (state.stage === "working") {
    if (claim?.status === "waiting") return { ...state, focus: null };
    if (claim && outcomeOf(claim)) {
      return {
        ...state,
        stage: "stamped",
        held: false,
        finished: [...state.finished, claim.claim_id],
      };
    }
  }
  if (
    state.stage === "stamped" &&
    state.held &&
    (active(state) || !state.running)
  ) {
    return { ...state, stage: "leaving" };
  }
  return state;
}

export function reduce(state: LiveState, event: LiveEvent): LiveState {
  switch (event.type) {
    case "poll":
      return settle({ ...state, claims: event.claims, running: event.running });
    case "held":
      return settle({ ...state, held: true });
    case "left":
      return settle({ ...state, focus: null, stage: "working", held: false });
  }
}

export interface Tally {
  counts: Record<LiveOutcome, number>;
  paid: number;
  awaiting: number;
}

export function tally(state: LiveState): Tally {
  const counts: Record<LiveOutcome, number> = {
    approve: 0,
    decline: 0,
    refer: 0,
    sign_off: 0,
  };
  let paid = 0;
  let awaiting = 0;
  for (const claim of state.claims) {
    const outcome = outcomeOf(claim);
    if (!outcome || !state.finished.includes(claim.claim_id)) continue;
    counts[outcome] += 1;
    if (outcome === "approve") paid += claim.payout ?? 0;
    if (outcome === "sign_off") awaiting += claim.payout ?? 0;
  }
  return { counts, paid, awaiting };
}

/** Where the live view is: "Claim 4 of 25". */
export function progress(state: LiveState): {
  position: number;
  total: number;
} {
  const remaining = state.claims.filter(
    (claim) =>
      !state.finished.includes(claim.claim_id) &&
      (claim.status === "waiting" || claim.status === "in_progress"),
  ).length;
  const done = state.finished.length;
  const position = state.stage === "working" && state.focus ? done + 1 : done;
  return { position, total: done + remaining };
}
