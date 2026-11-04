import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Run } from "./api";
import { LiveView } from "./LiveView";
import { runClaim, runRecord, stubBackend } from "./testing";

let reducedMotion = true;

beforeEach(() => {
  vi.useFakeTimers();
  reducedMotion = true;
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

function show(run: Run | null) {
  const routes: Record<string, unknown> = { "/api/runs/current": run };
  stubBackend(routes);
  return routes;
}

function card(claimId: string) {
  return screen.getByRole("article", { name: `Claim ${claimId}` });
}

const working = runRecord({
  total: 4,
  claims: [
    runClaim({ claim_id: "CLM-1001", status: "waiting" }),
    runClaim({
      claim_id: "CLM-1002",
      status: "in_progress",
      agent_working: true,
      latest_step: 'read_section {"number": 3}',
      cost: 0.0042,
      seconds: 12,
    }),
    runClaim({
      claim_id: "CLM-1003",
      status: "in_progress",
      agent_working: true,
      latest_step: null,
    }),
    runClaim({
      claim_id: "CLM-1004",
      status: "decided",
      decision: "decline",
      payout: 0,
    }),
  ],
  cost: 0.0042,
  elapsed: 75,
});

it("shows several claims worked at once as cards, the ones at work first", async () => {
  show(working);
  render(<LiveView />);
  await wait(10);
  const cards = within(screen.getByRole("list", { name: "Dispatch 1" }))
    .getAllByRole("article")
    .map((article) => article.getAttribute("aria-label"));
  expect(cards).toEqual([
    "Claim CLM-1002",
    "Claim CLM-1003",
    "Claim CLM-1004",
    "Claim CLM-1001",
  ]);
  expect(card("CLM-1002").textContent).toContain('read_section {"number": 3}');
  expect(card("CLM-1002").textContent).toContain("$0.0042 · 12s");
  expect(card("CLM-1003").textContent).toContain("Starting");
  expect(card("CLM-1001").textContent).toContain("Waiting for a claim agent");
  expect(within(card("CLM-1004")).getByRole("status").textContent).toBe(
    "Declined",
  );
  expect(screen.getByText("1 of 4 done · 2 at work")).toBeDefined();
  expect(screen.getByLabelText("Cost and time").textContent).toBe(
    "$0.0042 · 1m 15s",
  );
});

it("stamps each claim as it ends, an approval once it's paid", async () => {
  const routes = show(working);
  render(<LiveView />);
  await wait(10);
  expect(within(card("CLM-1002")).queryByRole("status")).toBeNull();

  routes["/api/runs/current"] = runRecord({
    ...working,
    claims: [
      runClaim({ claim_id: "CLM-1001", status: "in_progress" }),
      runClaim({
        claim_id: "CLM-1002",
        status: "decided",
        decision: "approve",
        payout: 420,
        paid: true,
      }),
      runClaim({
        claim_id: "CLM-1003",
        status: "awaiting_sign_off",
        decision: "approve",
        payout: 2240,
      }),
      runClaim({ claim_id: "CLM-1004", status: "needs_handler" }),
    ],
  });
  await wait(1000);
  expect(within(card("CLM-1002")).getByRole("status").textContent).toBe(
    "Approved$420.00",
  );
  expect(within(card("CLM-1003")).getByRole("status").textContent).toBe(
    "Waiting for sign-off$2,240.00",
  );
  expect(within(card("CLM-1004")).getByRole("status").textContent).toBe(
    "Left for a handler",
  );
  const tally = screen.getByRole("list", { name: "Outcomes so far" });
  expect(tally.textContent).toContain("1 Approved");
  expect(tally.textContent).toContain("1 Waiting for sign-off");
});

it("counts the payout up unless motion is reduced", async () => {
  reducedMotion = false;
  show(
    runRecord({
      total: 1,
      claims: [
        runClaim({ status: "decided", decision: "approve", payout: 400 }),
      ],
    }),
  );
  render(<LiveView />);
  await wait(10);
  expect(screen.getByRole("status").textContent).not.toBe("Approved$400.00");
  await wait(1000);
  expect(screen.getByRole("status").textContent).toBe("Approved$400.00");
});

it("ends on the summary from the records", async () => {
  show(
    runRecord({
      status: "finished",
      total: 2,
      claims: [
        runClaim({
          claim_id: "CLM-1001",
          status: "decided",
          decision: "approve",
          payout: 420,
        }),
        runClaim({
          claim_id: "CLM-1008",
          status: "awaiting_sign_off",
          decision: "approve",
          payout: 2240,
        }),
      ],
      summary: {
        approved: 2,
        declined: 0,
        referred: 0,
        awaiting_sign_off: [{ claim_id: "CLM-1008", payout: 2240 }],
        left_for_handler: [],
        in_progress: [],
      },
    }),
  );
  render(<LiveView />);
  await wait(10);
  expect(
    screen.getByRole("heading", { name: "The dispatch is done" }),
  ).toBeDefined();
  expect(
    screen.getByText("2 of 2 claims worked by 3 claim agents at once"),
  ).toBeDefined();
  expect(screen.getByText(/Payouts approved/).textContent).toBe(
    "Payouts approved: $420.00, and $2,240.00 waiting for sign-off",
  );
  expect(screen.getByText(/Waiting for a sign-off/).textContent).toContain(
    "CLM-1008 $2,240.00",
  );
});

it("says when a dispatch stopped partway", async () => {
  show(
    runRecord({
      status: "stopped",
      total: 1,
      claims: [runClaim({ status: "in_progress" })],
      summary: {
        approved: 0,
        declined: 0,
        referred: 0,
        awaiting_sign_off: [],
        left_for_handler: [],
        in_progress: ["CLM-1001"],
      },
    }),
  );
  render(<LiveView />);
  await wait(10);
  expect(
    screen.getByRole("heading", { name: "The dispatch stopped partway" }),
  ).toBeDefined();
  expect(screen.getByText(/Still in progress/).textContent).toBe(
    "Still in progress: CLM-1001",
  );
});

it("waits for a first dispatch", async () => {
  show(null);
  render(<LiveView />);
  await wait(10);
  expect(
    screen.getByText("No dispatch yet. Start one on the queue page."),
  ).toBeDefined();
});

it("leaves on Esc", async () => {
  window.location.hash = "#/live";
  show(null);
  render(<LiveView />);
  fireEvent.keyDown(window, { key: "Escape" });
  await wait(10);
  expect(window.location.hash).toBe("#/");
});
