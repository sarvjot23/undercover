import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Step } from "./api";
import { ClaimView } from "./ClaimView";
import { claim, pathOf, stubBackend } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const handlers = [
  { handler_id: "HND-01", name: "Dana Whitfield", role: "Senior" },
  { handler_id: "HND-02", name: "Marcus Oyelaran", role: "Handler" },
];

const step: Step = {
  step_id: 1,
  kind: "tool_call",
  text: 'get_claim {"claim_id": "CLM-1001"}',
  at: "2026-10-21T12:00:00+00:00",
};

const approval = {
  decision: "approve" as const,
  payout: 1200,
  reasons: "Covered by the wording.",
  policy_section: "5. Baggage and Personal Effects",
  decided_at: "2026-10-21T12:00:00+00:00",
};

function calls(fetchMock: ReturnType<typeof stubBackend>, path: string) {
  return fetchMock.mock.calls.filter(([input]) => pathOf(input) === path)
    .length;
}

it("shows the claim in full", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim(),
    "/api/claims/CLM-1001/steps": [],
  });
  render(<ClaimView claimId="CLM-1001" />);
  expect(
    await screen.findByText("My flight home from Rome was canceled."),
  ).toBeDefined();
  expect(screen.getByText("$420.00")).toBeDefined();
  expect(screen.getByText("Meridian Air cancellation notice")).toBeDefined();
  expect(screen.getByText("UnderCover Premium")).toBeDefined();
  expect(screen.getByText(/Checked bag arrived 30 hours late/)).toBeDefined();
  expect(screen.getByText("No decision yet.")).toBeDefined();
  expect(
    screen.getByText("The agent hasn’t worked on this claim."),
  ).toBeDefined();
});

it("says when the claim doesn't exist", async () => {
  stubBackend({});
  render(<ClaimView claimId="CLM-9999" />);
  expect((await screen.findByRole("alert")).textContent).toBe(
    "There is no claim CLM-9999.",
  );
});

it("runs the agent and follows its steps until it decides", async () => {
  const routes: Record<string, unknown> = {
    "/api/claims/CLM-1001": claim(),
    "/api/claims/CLM-1001/steps": [],
    "POST /api/claims/CLM-1001/run": { thread_id: "t" },
  };
  const fetchMock = stubBackend(routes);
  render(<ClaimView claimId="CLM-1001" />);
  fireEvent.click(await screen.findByRole("button", { name: "Run the agent" }));
  expect(calls(fetchMock, "/api/claims/CLM-1001/run")).toBe(1);

  routes["/api/claims/CLM-1001"] = claim({
    status: "in_progress",
    agent_working: true,
  });
  routes["/api/claims/CLM-1001/steps"] = [step];
  expect(
    await screen.findByText(step.text, {}, { timeout: 3000 }),
  ).toBeDefined();

  // Decided, but the agent is still paying the claim.
  routes["/api/claims/CLM-1001"] = claim({
    status: "decided",
    agent_working: true,
    decision: { ...approval, payout: 420 },
  });
  expect(
    await screen.findByText(/^Approved/, {}, { timeout: 3000 }),
  ).toBeDefined();

  const answer: Step = { ...step, step_id: 2, kind: "answer", text: "Paid." };
  routes["/api/claims/CLM-1001/steps"] = [step, answer];
  routes["/api/claims/CLM-1001"] = claim({
    status: "decided",
    decision: { ...approval, payout: 420 },
  });
  expect(await screen.findByText("Paid.", {}, { timeout: 3000 })).toBeDefined();
  const settled = calls(fetchMock, "/api/claims/CLM-1001");
  await new Promise((resolve) => setTimeout(resolve, 1500));
  expect(calls(fetchMock, "/api/claims/CLM-1001")).toBe(settled);
});

it("says when the agent can't start", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim(),
    "/api/claims/CLM-1001/steps": [],
  });
  render(<ClaimView claimId="CLM-1001" />);
  fireEvent.click(await screen.findByRole("button", { name: "Run the agent" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The agent couldn't start on this claim.",
  );
});

it("signs off a payout over the limit", async () => {
  const routes: Record<string, unknown> = {
    "/api/claims/CLM-1001": claim({
      status: "awaiting_sign_off",
      decision: approval,
    }),
    "/api/claims/CLM-1001/steps": [step],
    "/api/handlers": handlers,
    "POST /api/claims/CLM-1001/sign-off": { status: "decided" },
  };
  const fetchMock = stubBackend(routes);
  render(<ClaimView claimId="CLM-1001" />);
  const select = await screen.findByRole("combobox");
  await screen.findByRole("option", { name: "Marcus Oyelaran" });
  fireEvent.change(select, { target: { value: "HND-02" } });

  routes["/api/claims/CLM-1001"] = claim({
    status: "decided",
    decision: approval,
    payment: {
      amount: 1200,
      signed_off_by: "HND-02",
      paid_at: "2026-10-21T12:05:00+00:00",
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign off" }));
  expect(
    await screen.findByText(/signed off by Marcus Oyelaran/),
  ).toBeDefined();
  const signOff = fetchMock.mock.calls.find(
    ([input]) => pathOf(input) === "/api/claims/CLM-1001/sign-off",
  );
  expect(signOff?.[1]?.body).toBe(JSON.stringify({ handler_id: "HND-02" }));
  expect(screen.queryByRole("button", { name: "Sign off" })).toBeNull();
});

it("says when the sign-off fails", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim({
      status: "awaiting_sign_off",
      decision: approval,
    }),
    "/api/claims/CLM-1001/steps": [],
    "/api/handlers": handlers,
  });
  render(<ClaimView claimId="CLM-1001" />);
  await screen.findByRole("option", { name: "Dana Whitfield" });
  fireEvent.click(screen.getByRole("button", { name: "Sign off" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The sign-off didn't go through.",
  );
});

it("shows a decline and a policy with add-ons and no history", async () => {
  const base = claim();
  stubBackend({
    "/api/claims/CLM-1001": claim({
      status: "decided",
      decision: { ...approval, decision: "decline", payout: 0 },
      policy: { ...base.policy, add_ons: ["electronics_plus"] },
      customer: { ...base.customer, previous_claims: [] },
    }),
    "/api/claims/CLM-1001/steps": [],
  });
  render(<ClaimView claimId="CLM-1001" />);
  expect(await screen.findByText(/^Declined/)).toBeDefined();
  expect(screen.getByText("Electronics plus")).toBeDefined();
  expect(screen.getByText("None.")).toBeDefined();
});
