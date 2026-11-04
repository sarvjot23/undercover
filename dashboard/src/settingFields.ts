import type { PlatformSettings } from "./api";
import { money } from "./format";

export const GROUPS = {
  payouts: "Payouts",
  objectives: "Business objectives",
  noise: "Noise",
  tolerance: "Tolerance",
  rounds: "Rounds of improvement",
} as const;

export interface Field {
  /** Where the setting is kept, such as noise.accuracy. */
  name: string;
  group: keyof typeof GROUPS;
  label: string;
  unit: "$" | "%" | "points" | "agents";
  /** How the stored value is shown: a share of 1 is shown as a percentage. */
  scale: number;
  help: string;
}

const MEASURES = [
  ["accuracy", "Accuracy", "points", "percentage points"],
  ["grade", "Grade", "points", "points of the judge's grade, from 0 to 3"],
  ["cost_per_claim", "Cost per claim", "%", "of the old cost"],
  ["seconds_per_claim", "Time per claim", "%", "of the old time"],
] as const;

function margins(group: "noise" | "tolerance"): Field[] {
  const verb =
    group === "noise" ? "Counts as better only past" : "May get worse by up to";
  return MEASURES.map(([name, label, unit, what]) => ({
    name: `${group}.${name}`,
    group,
    label,
    unit,
    scale: unit === "%" || name === "accuracy" ? 100 : 1,
    help: `${verb} this many ${what}.`,
  }));
}

export const FIELDS: Field[] = [
  {
    name: "approval_limit",
    group: "payouts",
    label: "Approval limit",
    unit: "$",
    scale: 1,
    help: "A payout over this waits for a handler's sign-off. A new limit applies to later decisions.",
  },
  {
    name: "objectives.accuracy",
    group: "objectives",
    label: "Held-out accuracy, at least",
    unit: "%",
    scale: 100,
    help: "A new version below this is rolled back.",
  },
  {
    name: "objectives.grade",
    group: "objectives",
    label: "Held-out grade, at least",
    unit: "points",
    scale: 1,
    help: "The judge's average grade, from 0 (F) to 3 (A).",
  },
  ...margins("noise"),
  ...margins("tolerance"),
  {
    name: "round_spending_limit",
    group: "rounds",
    label: "Spending limit for a round",
    unit: "$",
    scale: 1,
    help: "The improver, its evaluations and the judge, all together.",
  },
  {
    name: "agents_at_once",
    group: "rounds",
    label: "Claim agents at once",
    unit: "agents",
    scale: 1,
    help: "In the improver's evaluations, from 1 to 25.",
  },
];

type Loose = Record<string, number | Record<string, number> | undefined>;

/** A setting's name in two parts, such as noise and accuracy. */
function parts(name: string): [string, string | undefined] {
  const dot = name.indexOf(".");
  return dot < 0
    ? [name, undefined]
    : [name.slice(0, dot), name.slice(dot + 1)];
}

/** A setting's stored value, by its name. */
export function read(settings: PlatformSettings, name: string): number {
  const [group, key] = parts(name);
  const top = (settings as unknown as Loose)[group];
  if (typeof top === "number") return top;
  if (top === undefined || key === undefined) return 0;
  return top[key] ?? 0;
}

/** The settings with one value changed. */
export function write(
  settings: PlatformSettings,
  name: string,
  value: number,
): PlatformSettings {
  const [group, key] = parts(name);
  if (key === undefined) return { ...settings, [group]: value };
  const nested = settings as unknown as Record<string, Record<string, number>>;
  return { ...settings, [group]: { ...nested[group], [key]: value } };
}

/** The value as a handler edits it, such as 60 for an accuracy of 0.6. */
export function stored(field: Field, value: number): number {
  return Math.round(value * field.scale * 1e6) / 1e6;
}

/** The value as a handler reads it, with its unit. */
export function shown(field: Field, value: number): string {
  if (field.unit === "$") return money(value);
  const number = stored(field, value);
  if (field.unit === "%") return `${String(number)}%`;
  if (field.unit === "agents") return String(number);
  return `${String(number)} points`;
}
