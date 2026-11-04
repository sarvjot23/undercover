import type { Round, RoundStage } from "./api";

/** One version's held-out scores, as the chart plots it. */
export interface ChartPoint {
  version: number;
  accuracy: number;
  grade: number | null;
  kept: boolean | null;
}

/** Version 1's held-out scores, then each version tried, oldest first. */
export function chartPoints(rounds: Round[]): ChartPoint[] {
  const oldest = [...rounds].reverse();
  const points: ChartPoint[] = [];
  const first = oldest.find((round) => round.before);
  if (first?.before?.accuracy !== undefined) {
    points.push({
      version: first.version_before,
      accuracy: first.before.accuracy,
      grade: first.before.grade ?? null,
      kept: null,
    });
  }
  for (const round of oldest) {
    if (round.version_tried !== null && round.after?.accuracy !== undefined) {
      points.push({
        version: round.version_tried,
        accuracy: round.after.accuracy,
        grade: round.after.grade ?? null,
        kept: round.verdict === "kept",
      });
    }
  }
  return points;
}

/** A round's stages in order, as the Improvement page shows them. */
export const STAGES: [RoundStage, string][] = [
  ["first_evaluations", "First evaluations"],
  ["improving", "The improver at work"],
  ["change_waiting", "A change waiting for approval"],
  ["evaluations", "Evaluations"],
  ["verdict", "The verdict"],
  ["recipe_waiting", "A recipe waiting for approval"],
  ["finished", "Finished"],
];

/** Where a round shows on the steps: once it has a verdict, the improver's work
 * on its recipe follows the verdict. */
export function shownStage(round: Round): RoundStage {
  if (round.stage === "improving" && round.verdict !== null) return "verdict";
  return round.stage;
}

export const ROUND_STATUS: Record<Round["status"], string> = {
  working: "Working",
  waiting: "Waiting for approval",
  finished: "Finished",
  stopped: "Stopped",
};

export const VERDICTS: Record<NonNullable<Round["verdict"]>, string> = {
  kept: "Kept",
  rolled_back: "Rolled back",
};

/** Whether a round is still open: working, or waiting for a handler. */
export function isOpen(round: Round): boolean {
  return round.status === "working" || round.status === "waiting";
}
