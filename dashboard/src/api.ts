export type Status =
  "waiting" | "in_progress" | "awaiting_sign_off" | "decided";
export type Outcome = "approve" | "decline" | "refer";

export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  claim_type: string;
  summary: string;
  amount_claimed: number;
  submitted_on: string;
  status: Status;
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
  kind: "tool_call" | "tool_result" | "answer" | "error";
  text: string;
  at: string;
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
