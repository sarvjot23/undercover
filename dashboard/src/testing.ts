import { vi } from "vitest";
import type { Claim, ClaimSummary } from "./api";

export function pathOf(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : input.toString();
}

/** Stub fetch so each path returns its JSON, and any other a 404. Key POSTs as "POST <path>". */
export function stubBackend(routes: Record<string, unknown>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(input);
    const body = routes[init?.method === "POST" ? `POST ${path}` : path];
    return Promise.resolve(
      body === undefined
        ? new Response("{}", { status: 404 })
        : new Response(JSON.stringify(body)),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function summary(overrides: Partial<ClaimSummary> = {}): ClaimSummary {
  return {
    claim_id: "CLM-1001",
    customer_name: "Maya Patel",
    claim_type: "trip_delay",
    summary: "Flight home canceled by the airline",
    amount_claimed: 420,
    submitted_on: "2026-06-24",
    status: "waiting",
    agent_working: false,
    decision: null,
    payout: null,
    ...overrides,
  };
}

export function claim(overrides: Partial<Claim> = {}): Claim {
  return {
    claim_id: "CLM-1001",
    claim_type: "trip_delay",
    submitted_on: "2026-06-24",
    incident_date: "2026-06-18",
    incident_location: "Rome, Italy",
    summary: "Flight home canceled by the airline",
    story: "My flight home from Rome was canceled.",
    items: [
      {
        description: "Airport hotel, one night",
        category: "accommodation",
        amount: 245,
      },
      { description: "Dinner and breakfast", category: "meals", amount: 95 },
      { description: "Taxis", category: "transport", amount: 80 },
    ],
    amount_claimed: 420,
    documents: [
      {
        name: "Meridian Air cancellation notice",
        type: "carrier_report",
        content: "Flight MA 611 was canceled.",
      },
    ],
    status: "waiting",
    agent_working: false,
    policy: {
      policy_id: "POL-2001",
      plan: "premium",
      add_ons: [],
      purchased_on: "2026-04-22",
      trip: {
        destination: "Rome, Italy",
        departs_on: "2026-06-10",
        returns_on: "2026-06-18",
      },
      travelers: ["Maya Patel"],
    },
    plan: { plan: "premium", name: "UnderCover Premium", deductible: 50 },
    customer: {
      customer_id: "CUS-3001",
      name: "Maya Patel",
      customer_since: "2023-04-11",
      previous_claims: [
        {
          claim_id: "CLM-0412",
          filed_on: "2024-08-19",
          claim_type: "baggage_delay",
          summary: "Checked bag arrived 30 hours late",
          outcome: "approved",
          amount_paid: 140,
        },
      ],
    },
    decision: null,
    payment: null,
    ...overrides,
  };
}
