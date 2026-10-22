import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ClaimSummary } from "./api";
import { LiveView } from "./LiveView";
import { claim, stubBackend, summary } from "./testing";

let reducedMotion = false;

beforeEach(() => {
  vi.useFakeTimers();
  reducedMotion = false;
  vi.stubGlobal("matchMedia", () => ({ matches: reducedMotion }));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Advance time until `check` passes, as the polls and timers run. */
async function until(check: () => void) {
  for (let i = 0; i < 40; i++) {
    try {
      check();
      return;
    } catch {
      await wait(250);
    }
  }
  check();
}

function stamp() {
  return screen.getByRole("status");
}

function backend(claims: ClaimSummary[], running = true) {
  const routes: Record<string, unknown> = {
    "/api/claims": claims,
    "/api/queue/run": { running },
    "/api/claims/CLM-1001/steps": [
      { step_id: 1, kind: "tool_call", text: "get_claim CLM-1001", at: "" },
    ],
    "/api/claims/CLM-1002/steps": [],
  };
  for (const item of claims) {
    routes[`/api/claims/${item.claim_id}`] = claim({
      claim_id: item.claim_id,
      status: item.status,
      agent_working: item.status === "in_progress",
    });
  }
  stubBackend(routes);
  return routes;
}

it("shows each claim full screen, stamps it and moves on to a summary", async () => {
  const routes = backend([
    summary({ status: "in_progress" }),
    summary({ claim_id: "CLM-1002" }),
  ]);
  render(<LiveView />);
  await wait(100);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "Flight home canceled by the airline",
  );
  expect(screen.getByText("Claim 1 of 2")).toBeDefined();
  expect(screen.getByText("get_claim CLM-1001")).toBeDefined();
  expect(screen.queryByRole("status")).toBeNull();

  routes["/api/claims"] = [
    summary({ status: "decided", decision: "approve", payout: 420 }),
    summary({ claim_id: "CLM-1002" }),
  ];
  routes["/api/claims/CLM-1001"] = claim({
    status: "decided",
    decision: {
      decision: "approve",
      payout: 420,
      reasons: "The delay is covered.",
      policy_section: "3. Trip Delay",
      decided_at: "",
    },
  });
  await until(() => {
    expect(stamp().textContent).toContain("Approved");
  });
  await until(() => {
    expect(stamp().textContent).toContain("$420.00");
  });
  expect(stamp().textContent).toContain("The delay is covered.");
  expect(
    screen.getByRole("list", { name: "Outcomes so far" }).textContent,
  ).toContain("1 Approved");

  routes["/api/claims"] = [
    summary({ status: "decided", decision: "approve", payout: 420 }),
    summary({ claim_id: "CLM-1002", status: "in_progress" }),
  ];
  routes["/api/claims/CLM-1002"] = claim({
    claim_id: "CLM-1002",
    summary: "Suitcase lost",
    status: "in_progress",
    agent_working: true,
  });
  await wait(500);
  expect(screen.getByRole("article").getAttribute("aria-label")).toBe(
    "Claim CLM-1001",
  );
  await until(() => {
    expect(screen.getByRole("article").getAttribute("aria-label")).toBe(
      "Claim CLM-1002",
    );
  });
  expect(screen.getByText("Claim 2 of 2")).toBeDefined();

  routes["/api/claims"] = [
    summary({ status: "decided", decision: "approve", payout: 420 }),
    summary({
      claim_id: "CLM-1002",
      status: "awaiting_sign_off",
      decision: "approve",
      payout: 1200,
    }),
  ];
  routes["/api/queue/run"] = { running: false };
  await until(() => {
    expect(stamp().textContent).toContain("Waiting for sign-off");
  });
  await until(() => {
    expect(
      screen.getByRole("heading", { name: "The queue is done" }),
    ).toBeDefined();
  });
  expect(screen.getByText(/Payouts approved/).textContent).toBe(
    "Payouts approved: $420.00, and $1,200.00 waiting for sign-off",
  );
});

it.each([
  ["decline", "Declined"],
  ["refer", "Referred"],
] as const)("stamps a %s", async (decision, word) => {
  backend([summary({ status: "in_progress" })]);
  render(<LiveView />);
  await wait(100);
  backend([summary({ status: "decided", decision, payout: 0 })]);
  await until(() => {
    expect(stamp().textContent).toBe(word);
  });
});

it("shows the payout at once with reduced motion", async () => {
  reducedMotion = true;
  backend([summary({ status: "in_progress" })]);
  render(<LiveView />);
  await wait(100);
  backend([summary({ status: "decided", decision: "approve", payout: 75 })]);
  await until(() => {
    expect(stamp().textContent).toContain("$75.00");
  });
});

it("waits for the agent, and can start the queue", async () => {
  backend([summary()], false);
  const fullscreen = vi.fn().mockResolvedValue(undefined);
  document.documentElement.requestFullscreen = fullscreen;
  render(<LiveView />);
  await wait(100);
  expect(
    screen.getByText("Waiting for the agent to pick up a claim"),
  ).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Run the queue" }));
  expect(fullscreen).toHaveBeenCalled();
});

it("leaves on Esc", async () => {
  backend([summary()], false);
  window.location.hash = "#/live";
  render(<LiveView />);
  await wait(100);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(window.location.hash).toBe("#/");
});
