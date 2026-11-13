import type { Handler, Outcome, SetName, Status } from "./api";

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export function money(amount: number): string {
  return dollars.format(amount);
}

const cents = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

/** A model cost, which is often a fraction of a cent. */
export function cost(amount: number): string {
  return cents.format(amount);
}

/** A share, such as 0.8, as a percentage. */
export function percent(share: number): string {
  return `${String(Math.round(share * 100))}%`;
}

/** A length of time, such as 42s or 3m 05s. */
export function duration(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = String(whole % 60);
  return minutes === 0
    ? `${rest}s`
    : `${String(minutes)}m ${rest.padStart(2, "0")}s`;
}

export function date(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function label(code: string): string {
  const words = code.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const STATUS_LABELS: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  awaiting_sign_off: "Waiting for sign-off",
  sent_back: "Sent back",
  decided: "Decided",
  needs_handler: "Left for a handler",
};

export const OUTCOME_LABELS: Record<Outcome, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};

export const SET_LABELS: Record<SetName, string> = {
  evaluation: "Evaluation set",
  held_out: "Held-out set",
};

/** Which claims of the set an evaluation works: all of them, or the five tiny ones. */
export function claimsLabel(tiny: boolean): string {
  return tiny ? "Five tiny claims" : "The whole set";
}

/** Who proposed or approved a version: a handler by name, the improver or the seed. */
export function byWhom(
  who: string | null,
  handlers: Handler[] | undefined,
): string {
  if (who === null || who === "seed") return "Seeded";
  if (who === "improver") return "The improver";
  return handlers?.find((handler) => handler.handler_id === who)?.name ?? who;
}

/** The judge's grade: its letter and score, such as B (2.10). */
export function grade(letter: string | null, score: number | null): string {
  if (letter === null || score === null) return "Not graded";
  return `${letter} (${score.toFixed(2)})`;
}

/** One of the judge's checks, kept as a probability and shown as yes or no. */
export function check(probability: number | null): string {
  if (probability === null) return "";
  return probability >= 0.5 ? "Yes" : "No";
}

/** An average grade from 0 to 3, or why there's none. */
export function averageGrade(score: number | null): string {
  return score === null ? "Not graded" : score.toFixed(2);
}

/** A model without its provider, such as gpt-6-luna for openai/gpt-6-luna. */
export function shortModel(model: string): string {
  return model.slice(model.indexOf("/") + 1);
}
