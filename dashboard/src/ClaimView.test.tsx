import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Step } from "./api";
import { ClaimView } from "./ClaimView";
import { claim, dana, marcus, pathOf, renderAs, stubBackend } from "./testing";

vi.mock("./auth");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const handlers = [dana, marcus];

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
  approval_limit: 800,
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
  await waitFor(() => {
    expect(calls(fetchMock, "/api/claims/CLM-1001/run")).toBe(1);
  });

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
  // Let the last poll that was already due land, then expect no more.
  await new Promise((resolve) => setTimeout(resolve, 1200));
  const settled = calls(fetchMock, "/api/claims/CLM-1001");
  await new Promise((resolve) => setTimeout(resolve, 1500));
  expect(calls(fetchMock, "/api/claims/CLM-1001")).toBe(settled);
}, 10_000);

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

it("signs off a payout over the limit as the handler signed in", async () => {
  const routes: Record<string, unknown> = {
    "/api/claims/CLM-1001": claim({
      status: "awaiting_sign_off",
      decision: approval,
    }),
    "/api/claims/CLM-1001/steps": [step],
    "/api/handlers": handlers,
    "POST /api/claims/CLM-1001/sign-off": { status: "in_progress" },
  };
  const fetchMock = stubBackend(routes);
  renderAs(dana, <ClaimView claimId="CLM-1001" />);
  const button = await screen.findByRole("button", {
    name: "Sign off as Dana Whitfield",
  });
  expect(screen.queryByRole("combobox")).toBeNull();

  const signed = {
    handler_id: "HND-01",
    signed_off_at: "2026-10-21T12:04:00+00:00",
  };
  routes["/api/claims/CLM-1001"] = claim({
    status: "in_progress",
    agent_working: true,
    decision: approval,
    sign_off: signed,
  });
  fireEvent.click(button);
  expect(await screen.findByText(/The agent\s+is paying it/)).toBeDefined();
  expect(screen.getByText("In progress")).toBeDefined();

  routes["/api/claims/CLM-1001"] = claim({
    status: "decided",
    decision: approval,
    sign_off: signed,
    payment: {
      amount: 1200,
      signed_off_by: "HND-01",
      signed_off_at: signed.signed_off_at,
      paid_at: "2026-10-21T12:05:00+00:00",
    },
  });
  expect(
    await screen.findByText(/signed off by Dana Whitfield/, undefined, {
      timeout: 3000,
    }),
  ).toBeDefined();
  const signOff = fetchMock.mock.calls.find(
    ([input]) => pathOf(input) === "/api/claims/CLM-1001/sign-off",
  );
  expect(signOff?.[1]?.body).toBeUndefined();
  expect(signOff?.[1]?.headers).toMatchObject({
    Authorization: "Bearer token-for-dana.whitfield@undercover.example",
  });
  expect(screen.queryByRole("button", { name: /Sign off/ })).toBeNull();
});

it("says why the sign-off was refused", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim({
      status: "awaiting_sign_off",
      decision: approval,
    }),
    "/api/claims/CLM-1001/steps": [],
    "/api/handlers": handlers,
  });
  renderAs(dana, <ClaimView claimId="CLM-1001" />);
  fireEvent.click(await screen.findByRole("button", { name: /Sign off/ }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The backend refused it.",
  );
});

it("tells Marcus why he can't sign off a held payout", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim({
      status: "awaiting_sign_off",
      decision: approval,
    }),
    "/api/claims/CLM-1001/steps": [],
    "/api/handlers": handlers,
  });
  renderAs(marcus, <ClaimView claimId="CLM-1001" />);
  expect(
    await screen.findByText(
      "Only a handler who can sign off payouts over the limit can sign this off.",
    ),
  ).toBeDefined();
  expect(screen.queryByRole("button", { name: /Sign off/ })).toBeNull();
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

it("lists the sections the agent read, and its failed attempts", async () => {
  const read = (step_id: number, text: string): Step => ({
    step_id,
    kind: "read",
    text,
    at: "2026-10-29T12:00:00+00:00",
  });
  stubBackend({
    "/api/claims/CLM-1005": claim({
      claim_id: "CLM-1005",
      status: "needs_handler",
      attempts: 2,
    }),
    "/api/claims/CLM-1005/steps": [
      step,
      read(2, "Policy wording · 6. Passport and Travel Documents"),
      read(3, "Claims manual · 7. Interpretation notes"),
      {
        step_id: 4,
        kind: "error",
        text: "The agent's run failed: timed out",
        at: "",
      },
    ],
    "/api/handlers": handlers,
  });
  render(<ClaimView claimId="CLM-1005" />);
  const reads = await screen.findByRole("region", {
    name: "What the agent read",
  });
  expect(
    Array.from(reads.querySelectorAll("li")).map((item) => item.textContent),
  ).toEqual([
    "Policy wording · 6. Passport and Travel Documents",
    "Claims manual · 7. Interpretation notes",
  ]);
  expect(screen.getByText("Left for a handler")).toBeDefined();
  expect(screen.getByText(/failed attempts/).textContent).toBe(
    "2 failed attempts",
  );
  expect(screen.getAllByText("Read")).toHaveLength(2);
});

it("shows a copy for an evaluation with no sign-off form and no run button", async () => {
  stubBackend({
    "/api/claims/EV7-CLM-1021": claim({
      claim_id: "EV7-CLM-1021",
      status: "awaiting_sign_off",
      decision: approval,
    }),
    "/api/claims/EV7-CLM-1021/steps": [step],
    "/api/claims/EV7-CLM-1021/standing": { evaluation_id: 7 },
    "/api/handlers": handlers,
  });
  render(<ClaimView claimId="EV7-CLM-1021" />);
  const note = await screen.findByText(/Nobody signs off a copy/);
  expect(note.textContent).toContain("A copy for evaluation 7.");
  expect(
    screen.getByRole("link", { name: "evaluation 7" }).getAttribute("href"),
  ).toBe("#/scoreboard/7");
  expect(screen.queryByRole("button", { name: "Sign off" })).toBeNull();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.queryByRole("button", { name: "Run the agent" })).toBeNull();
});
