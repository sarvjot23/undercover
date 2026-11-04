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
