import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { SourceFile, Step } from "./api";
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
  text: "get_claim {}",
  at: "2026-10-21T12:00:00+00:00",
  detail: null,
};

const approval = {
  decision: "approve" as const,
  payout: 1200,
  reasons: "Covered by the wording.",
  policy_section: "5. Baggage and Personal Effects",
  decided_at: "2026-10-21T12:00:00+00:00",
  decided_by: "UnderCover Agent, version 1",
  manual_version: "2026.2",
  calculation: {
    lines: [
      { step: "Clinic visit", amount: 1300 },
      { step: "Less the deductible", amount: -100 },
    ],
    payout: 1200,
  },
  approval_limit: 800,
  payment_refused: null,
};

const decline = {
  ...approval,
  decision: "decline" as const,
  payout: 0,
  calculation: null,
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

  const answer: Step = {
    step_id: 2,
    kind: "answer",
    text: "Paid.",
    at: "",
    detail: null,
  };
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

it("signs off a payout over the limit as the handler signed in, which pays it", async () => {
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
    status: "decided",
    decision: approval,
    sign_off: signed,
    payment: {
      amount: 1200,
      signed_off_by: "HND-01",
      signed_off_at: signed.signed_off_at,
      paid_at: signed.signed_off_at,
    },
  });
  fireEvent.click(button);
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
      "Only a handler who can sign off payouts over the limit can sign this off or send it back.",
    ),
  ).toBeDefined();
  expect(screen.queryByRole("button", { name: /Sign off/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "Send back" })).toBeNull();
});

it("sends a decision back with a note, which is required and limited", async () => {
  const routes: Record<string, unknown> = {
    "/api/claims/CLM-1001": claim({
      status: "awaiting_sign_off",
      decision: approval,
    }),
    "/api/claims/CLM-1001/steps": [],
    "/api/handlers": handlers,
    "POST /api/claims/CLM-1001/send-back": { status: "sent_back" },
  };
  const fetchMock = stubBackend(routes);
  renderAs(dana, <ClaimView claimId="CLM-1001" />);
  fireEvent.click(await screen.findByRole("button", { name: "Send back" }));
  const note = screen.getByLabelText("What should the agent look at again?");
  expect(note.getAttribute("maxLength")).toBe("1000");
  fireEvent.click(
    screen.getByRole("button", { name: "Send back to the agent" }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Say what the agent should look at again.",
  );
  expect(calls(fetchMock, "/api/claims/CLM-1001/send-back")).toBe(0);

  fireEvent.change(note, { target: { value: "Check the carrier's refund." } });
  expect(screen.getByText(/characters$/).textContent).toBe(
    "27 of 1,000 characters",
  );
  routes["/api/claims/CLM-1001"] = claim({ status: "sent_back" });
  fireEvent.click(
    screen.getByRole("button", { name: "Send back to the agent" }),
  );
  expect(
    await screen.findByText(/Waiting for the next dispatch/, undefined, {
      timeout: 3000,
    }),
  ).toBeDefined();
  const sent = fetchMock.mock.calls.find(
    ([input]) => pathOf(input) === "/api/claims/CLM-1001/send-back",
  );
  expect(JSON.parse(sent?.[1]?.body as string)).toEqual({
    note: "Check the carrier's refund.",
  });
});

it("shows each decision sent back with its note, who and when", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim({ status: "decided", decision: decline }),
    "/api/claims/CLM-1001/steps": [],
    "/api/handlers": handlers,
    "/api/claims/CLM-1001/sent-back": [
      {
        sent_back_id: 1,
        decision: approval,
        note: "The carrier already paid $350.",
        handler_id: "HND-01",
        handler_name: "Dana Whitfield",
        sent_back_at: "2026-10-21T12:04:00+00:00",
      },
    ],
  });
  renderAs(dana, <ClaimView claimId="CLM-1001" />);
  expect(
    await screen.findByText("The carrier already paid $350."),
  ).toBeDefined();
  expect(
    screen.getByText(/Dana Whitfield sent back approved/).textContent,
  ).toContain("$1,200.00");
  expect(screen.getByText("Declined")).toBeDefined();
  expect(screen.queryByText(/Waiting for the next dispatch/)).toBeNull();
});

it("shows a decline and a policy with add-ons and no history", async () => {
  const base = claim();
  stubBackend({
    "/api/claims/CLM-1001": claim({
      status: "decided",
      decision: decline,
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

const wording: SourceFile = {
  file: "policy_wording.md",
  system: "Legal",
  owner: "Legal",
  reviewed: "2026-09-01",
};
const manual: SourceFile = {
  file: "claims_manual.md",
  system: "Claims operations",
  owner: "Head of claims operations",
  reviewed: "2026-09-01",
};
const glossary: SourceFile = {
  file: "glossary.yaml",
  system: "The policy wording, version 2026.1",
  owner: "Legal",
  reviewed: "2026-08-15",
};

function lookup(step_id: number, looked_up: string, files: SourceFile[]): Step {
  return {
    step_id,
    kind: "lookup",
    text: looked_up,
    at: "",
    detail: { looked_up, files },
  };
}

it("lists the context the agent used by file, once each, and its failed attempts", async () => {
  stubBackend({
    "/api/claims/CLM-1005": claim({
      claim_id: "CLM-1005",
      status: "needs_handler",
      attempts: 2,
    }),
    "/api/claims/CLM-1005/steps": [
      step,
      lookup(2, "The term “Unattended”", [glossary]),
      lookup(3, "The documents, for “receipts”", [wording, manual]),
      lookup(4, "Claims manual · 7. Interpretation notes", [manual]),
      lookup(5, "Claims manual · 7. Interpretation notes", [manual]),
      lookup(6, "The documents, for “zeppelin”", []),
      {
        step_id: 7,
        kind: "error",
        text: "The agent's run failed: timed out",
        at: "",
        detail: null,
      },
    ],
    "/api/handlers": handlers,
  });
  render(<ClaimView claimId="CLM-1005" />);
  const used = await screen.findByRole("region", { name: "Context used" });
  const files = Array.from(used.querySelectorAll("section"));
  expect(files.map((file) => file.getAttribute("aria-label"))).toEqual([
    "glossary.yaml",
    "policy_wording.md",
    "claims_manual.md",
  ]);
  const listed = (file: Element | undefined) =>
    Array.from(file?.querySelectorAll("li") ?? []).map(
      (item) => item.textContent,
    );
  expect(listed(files[2])).toEqual([
    "The documents, for “receipts”",
    "Claims manual · 7. Interpretation notes",
  ]);
  expect(files[0]?.textContent).toContain(
    "The policy wording, version 2026.1, owned by Legal, reviewed",
  );
  expect(screen.getByText("Left for a handler")).toBeDefined();
  expect(screen.getByText(/failed attempts/).textContent).toBe(
    "2 failed attempts",
  );
});

it("shows the whole decision record with its calculation", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim({ status: "decided", decision: approval }),
    "/api/claims/CLM-1001/steps": [],
    "/api/handlers": handlers,
  });
  render(<ClaimView claimId="CLM-1001" />);
  const calculation = await screen.findByRole("table", { name: "Calculation" });
  expect(
    Array.from(calculation.querySelectorAll("tr")).map(
      (row) => row.textContent,
    ),
  ).toEqual([
    "Clinic visit$1,300.00",
    "Less the deductible-$100.00",
    "Payout$1,200.00",
  ]);
  expect(screen.getByText("UnderCover Agent, version 1")).toBeDefined();
  expect(screen.getByText("2026.2")).toBeDefined();
  expect(screen.getByText("5. Baggage and Personal Effects")).toBeDefined();
});

it("shows no calculation on a decline", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim({ status: "decided", decision: decline }),
    "/api/claims/CLM-1001/steps": [],
  });
  render(<ClaimView claimId="CLM-1001" />);
  expect(await screen.findByText(/^Declined/)).toBeDefined();
  expect(screen.queryByRole("table", { name: "Calculation" })).toBeNull();
});

it("says the Gateway refused the payment on the sign-off panel", async () => {
  stubBackend({
    "/api/claims/CLM-1001": claim({
      status: "awaiting_sign_off",
      decision: {
        ...approval,
        payout: 900,
        approval_limit: 1500,
        payment_refused: "Tool Execution Denied: payments over $1,000",
      },
    }),
    "/api/claims/CLM-1001/steps": [],
    "/api/handlers": handlers,
  });
  renderAs(dana, <ClaimView claimId="CLM-1001" />);
  expect(
    await screen.findByText(/The Gateway refused the payment/),
  ).toBeDefined();
  expect(screen.getByText(/Tool Execution Denied/)).toBeDefined();
  expect(screen.queryByText(/over the approval limit/)).toBeNull();
  expect(
    screen.getByRole("button", { name: "Sign off as Dana Whitfield" }),
  ).toBeDefined();
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

it("shows the security check's result as the first step", async () => {
  const found =
    "Instructions found: the story tells the handler to pay it in full.";
  stubBackend({
    "/api/claims/CLM-1901": claim({
      claim_id: "CLM-1901",
      status: "decided",
      decision: {
        decision: "refer",
        payout: 0,
        reasons: "The security check found an instruction in the claim.",
        policy_section: "Security check: instructions found in the claim",
        decided_at: "2026-11-07T12:00:00+00:00",
        decided_by: "Security check",
        manual_version: "2026.2",
        calculation: null,
        approval_limit: 800,
        payment_refused: null,
      },
    }),
    "/api/claims/CLM-1901/steps": [
      { step_id: 1, kind: "check", text: found, at: "", detail: null },
      {
        step_id: 2,
        kind: "answer",
        text: "CLM-1901: refer $0.00",
        at: "",
        detail: null,
      },
    ],
    "/api/handlers": handlers,
  });
  render(<ClaimView claimId="CLM-1901" />);
  expect(await screen.findByText(found)).toBeDefined();
  const first = screen.getByText(found).closest("li");
  expect(first?.querySelector(".step-kind")?.textContent).toBe(
    "Security check",
  );
  expect(first?.className).toContain("step-check");
});
