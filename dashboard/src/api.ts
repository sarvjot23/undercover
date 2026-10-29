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
}

export interface Payment {
  amount: number;
  signed_off_by: string | null;
  paid_at: string;
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
  payment: Payment | null;
}

export interface Step {
  step_id: number;
  kind: "tool_call" | "tool_result" | "read" | "answer" | "error";
  text: string;
  at: string;
}

export type TodoStatus = "to_do" | "in_progress" | "done" | "left_for_handler";

/** One item on the agent's to-do list for a run. */
export interface Todo {
  claim_id: string;
  note: string;
  status: TodoStatus;
}

/** A queue run: its cap, the claims it took, its to-do list and its summary. */
export interface Run {
  run_id: number;
  cap: number;
  total: number;
  status: "running" | "finished" | "failed";
  todos: Todo[];
  summary: string | null;
  claim_ids: string[];
  started_at: string;
  finished_at: string | null;
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${String(response.status)}`);
  return (await response.json()) as T;
}

export async function postJson<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${path}: ${String(response.status)}`);
  return (await response.json()) as T;
}
