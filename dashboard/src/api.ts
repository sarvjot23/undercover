import { accessToken } from "./auth";

export type Status =
  "waiting" | "in_progress" | "awaiting_sign_off" | "decided" | "needs_handler";
export type Outcome = "approve" | "decline" | "refer";

export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  claim_type: string;
  summary: string;
  amount_claimed: number;
  submitted_on: string;
  status: Status;
  attempts: number;
  agent_working: boolean;
  decision: Outcome | null;
  payout: number | null;
  thread_id: string | null;
  signed_off: boolean;
}

export interface Item {
  description: string;
  category: string;
  amount: number;
}

export interface Document {
  name: string;
  type: string;
  content: string;
}

export interface PreviousClaim {
  claim_id: string;
  filed_on: string;
  claim_type: string;
  summary: string;
  outcome: string;
  amount_paid: number;
}

export interface Decision {
  decision: Outcome;
  payout: number;
  reasons: string;
  policy_section: string;
  decided_at: string;
  /** The approval limit the decision was made under. */
  approval_limit: number;
}

export interface Payment {
  amount: number;
  signed_off_by: string | null;
  signed_off_at: string | null;
  paid_at: string;
}

export interface SignOff {
  handler_id: string;
  signed_off_at: string;
}

export interface Plan {
  plan: string;
  name: string;
  deductible: number;
  [limit: string]: string | number;
}

export interface Claim {
  claim_id: string;
  claim_type: string;
  submitted_on: string;
  incident_date: string;
  incident_location: string;
  summary: string;
  story: string;
  items: Item[];
  amount_claimed: number;
  documents: Document[];
  status: Status;
  attempts: number;
  agent_working: boolean;
  policy: {
    policy_id: string;
    plan: string;
    add_ons: string[];
    purchased_on: string;
    trip: { destination: string; departs_on: string; returns_on: string };
    travelers: string[];
  };
  plan: Plan;
  customer: {
    customer_id: string;
    name: string;
    customer_since: string;
    previous_claims: PreviousClaim[];
  };
  decision: Decision | null;
  sign_off: SignOff | null;
  payment: Payment | null;
}

export interface Step {
  step_id: number;
  kind: "tool_call" | "tool_result" | "read" | "answer" | "error";
  text: string;
  at: string;
}

export type SetName = "evaluation" | "held_out";

/** One of a run's claims: where it stands, its latest step, its cost and time. */
export interface RunClaim {
  claim_id: string;
  /** For an evaluation's copy, the claim it was copied from. */
  source_id: string | null;
  status: Status;
  attempts: number;
  agent_working: boolean;
  latest_step: string | null;
  decision: Outcome | null;
  payout: number | null;
  reasons: string | null;
  paid: boolean;
  cost: number;
  seconds: number;
  started: string | null;
}

/** An ended run's summary, built from the records with no model. */
export interface RunSummary {
  approved: number;
  declined: number;
  referred: number;
  awaiting_sign_off: { claim_id: string; payout: number }[];
  left_for_handler: string[];
  in_progress: string[];
}

/** A dispatch or an evaluation: its claims, cost and time, and its summary once ended. */
export interface Run {
  run_id: number;
  kind: "dispatch" | "evaluation";
  n: number;
  set_name: SetName | null;
  tiny: boolean;
  version: number;
  round_id: number | null;
  model: string;
  reasoning: string;
  total: number;
  status: "running" | "finished" | "stopped";
  started_at: string;
  finished_at: string | null;
  claims: RunClaim[];
  cost: number;
  seconds: number;
  elapsed: number;
  summary: RunSummary | null;
}

/** An evaluation's measures, from our team's labs. */
export interface Scores {
  decision_accuracy: number;
  accuracy: number;
  cost_of_mistakes: number;
  straight_through: number;
  cost: number;
  cost_per_claim: number;
  seconds_per_claim: number;
  seconds: number;
  /** The judge's average grade, from 0 (F) to 3 (A), or null if it graded nothing. */
  grade: number | null;
  judge_cost: number;
}

/** One claim of an evaluation: the handler's answer beside the agent's. */
export interface ScoredClaim extends RunClaim {
  handler_decision: Outcome;
  handler_payout: number;
  /** The agent's decision, with a claim it didn't decide counted as a referral. */
  agent_decision: Outcome;
  agent_payout: number;
  right: boolean;
  mistake_cost: number;
  /** The judge's grade on the explanation, unless it couldn't grade it. */
  graded: boolean;
  grade: number | null;
  letter: "F" | "C" | "B" | "A" | null;
  same_grounds: number | null;
  same_section: number | null;
  judge_cost: number;
}

/** An evaluation as the scoreboard lists it, with its measures once finished. */
export type EvaluationSummary = Omit<Run, "claims"> & { scores: Scores | null };

export interface Evaluation extends Run {
  claims: ScoredClaim[];
  scores: Scores | null;
}

/** One line of a diff: kept, added, removed, or a gap for unchanged lines left out. */
export interface DiffLine {
  kind: "same" | "add" | "remove" | "gap";
  text: string;
}

/** A version's scores on a set: the averages of the evaluations rounds ran on it. */
export type VersionScores = Partial<Scores> & { runs: number };

/** A version of the claim agent's configuration. */
export interface ConfigVersion {
  version: number;
  instructions: string;
  model: string;
  reasoning: string;
  reason: string;
  proposed_by: string;
  approved_by: string | null;
  approved_at: string;
  current: boolean;
  changed: string[];
  scores: { evaluation: VersionScores | null; held_out: VersionScores | null };
}

export interface VersionDiff {
  version: number;
  before: number | null;
  instructions: DiffLine[];
  model: [string | null, string];
  reasoning: [string | null, string];
}

export interface RecipeVersion {
  version: number;
  recipe: string;
  reason: string;
  proposed_by: string;
  approved_by: string | null;
  approved_at: string;
}

export interface RecipeDiff {
  version: number;
  before: number | null;
  recipe: DiffLine[];
}

export interface Margins {
  accuracy: number;
  grade: number;
  cost_per_claim: number;
  seconds_per_claim: number;
}

export interface PlatformSettings {
  approval_limit: number;
  objectives: { accuracy: number; grade: number };
  noise: Margins;
  tolerance: Margins;
  round_spending_limit: number;
  agents_at_once: number;
}

export interface SettingChange {
  change_id: number;
  name: string;
  before: number;
  after: number;
  handler_id: string;
  changed_at: string;
}

export interface AllowedModel {
  model: string;
  reasoning_efforts: string[];
  input_price: number;
  output_price: number;
}

export interface SettingsRecord {
  settings: PlatformSettings;
  changes: SettingChange[];
  models: AllowedModel[];
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
  email: string;
  can_approve_over_limit: boolean;
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${String(response.status)}`);
  return (await response.json()) as T;
}

/** POST as the signed-in handler, with their access token. */
async function post(path: string, body?: object, method = "POST") {
  const token = await accessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function postJson<T>(path: string, body?: object): Promise<T> {
  const response = await post(path, body);
  if (!response.ok) throw new Error(`${path}: ${String(response.status)}`);
  return (await response.json()) as T;
}

/** Send an action, and return the backend's reason when it refuses, or null. */
export async function postForRefusal(
  path: string,
  body?: object,
  method = "POST",
): Promise<string | null> {
  try {
    const response = await post(path, body, method);
    if (response.ok) return null;
    const refusal = (await response.json()) as { detail?: unknown };
    return typeof refusal.detail === "string"
      ? refusal.detail
      : "The backend refused it.";
  } catch {
    return "The backend is not responding.";
  }
}

export type RoundStage =
  | "first_evaluations"
  | "improving"
  | "change_waiting"
  | "evaluations"
  | "verdict"
  | "recipe_waiting"
  | "finished"
  | "stopped";

/** A new version of the claim agent's configuration, waiting for a handler. */
export interface ChangeProposal {
  kind: "change";
  instructions: string;
  model: string;
  reasoning: string;
  reason: string;
  diff: DiffLine[];
  model_before: string;
  reasoning_before: string;
}

/** A new version of the improver's recipe, waiting for a handler. */
export interface RecipeProposal {
  kind: "recipe";
  recipe: string;
  reason: string;
  diff: DiffLine[];
}

export interface RoundEvent {
  event_id: number;
  decision: "approve" | "reject";
  proposal: "change" | "recipe";
  handler_id: string;
  message: string;
  at: string;
}

/** A round of improvement, as the backend records it. */
export interface Round {
  round_id: number;
  thread_id: string;
  recipe_version: number;
  settings: PlatformSettings;
  status: "working" | "waiting" | "finished" | "stopped";
  stage: RoundStage;
  progress: string | null;
  proposal: ChangeProposal | RecipeProposal | null;
  version_before: number;
  version_tried: number | null;
  reason: string | null;
  before: VersionScores | null;
  after: VersionScores | null;
  verdict: "kept" | "rolled_back" | null;
  why: string | null;
  started_by: string;
  started_at: string;
  finished_at: string | null;
  tried: { version: number; model: string; reasoning: string } | null;
  events: RoundEvent[];
  evaluations: {
    run_id: number;
    set_name: SetName;
    version: number;
    status: Run["status"];
  }[];
  spent: number;
}
