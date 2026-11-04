import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { runClaim, runRecord, stubBackend, summary } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

const queue = [
  summary(),
  summary({
    claim_id: "CLM-1002",
    customer_name: "Tom Reyes",
    status: "awaiting_sign_off",
    decision: "approve",
    payout: 1250,
  }),
  summary({
    claim_id: "CLM-1003",
    status: "decided",
    decision: "decline",
    payout: 0,
  }),
];

it("shows the queue with each claim's status", async () => {
  stubBackend({ "/api/claims": queue });
  render(<App />);
  const rows = await screen.findAllByRole("row");
  expect(rows).toHaveLength(4);
  const second = within(rows[2]);
  expect(
    second.getByRole("link", { name: "CLM-1002" }).getAttribute("href"),
  ).toBe("#/claims/CLM-1002");
  expect(second.getByText("Waiting for sign-off")).toBeDefined();
  expect(second.getByText("$1,250.00")).toBeDefined();
  expect(second.getByText("Trip delay")).toBeDefined();
  expect(second.getByText("Jun 24, 2026")).toBeDefined();
});

it("counts the claims in each state", async () => {
  stubBackend({ "/api/claims": queue });
  render(<App />);
  const tiles = await screen.findAllByRole("listitem");
  expect(tiles.map((tile) => tile.textContent)).toEqual([
    "1Waiting",
    "0In progress",
    "1Waiting for sign-off",
    "1Decided",
    "0Left for a handler",
  ]);
});

it("says when the backend is down", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<App />);
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The backend is not responding.",
  );
});

it("shows the instructions read only", async () => {
  window.location.hash = "#/instructions";
  stubBackend({
    "/api/instructions": { claim: "You decide one claim." },
  });
  render(<App />);
  expect(await screen.findByText("You decide one claim.")).toBeDefined();
  expect(
    screen.queryByRole("heading", { name: "Working the queue" }),
  ).toBeNull();
  expect(
    screen.getByRole("heading", { name: "Working a claim" }),
  ).toBeDefined();
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(
    screen
      .getByRole("link", { name: "Instructions" })
      .getAttribute("aria-current"),
  ).toBe("page");
});

it("says when the instructions can't load", async () => {
  window.location.hash = "#/instructions";
  stubBackend({});
  render(<App />);
  expect(await screen.findByRole("alert")).toBeDefined();
});

it("leaves the live view and full screen", async () => {
  window.location.hash = "#/live";
  stubBackend({
    "/api/runs/current": null,
  });
  const exitFullscreen = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(document, "fullscreenElement", {
    configurable: true,
    value: document.documentElement,
  });
  document.exitFullscreen = exitFullscreen;
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Leave (Esc)" }));
  expect(exitFullscreen).toHaveBeenCalled();
  expect(window.location.hash).toBe("#/");
  Object.defineProperty(document, "fullscreenElement", {
    configurable: true,
    value: null,
  });
});

function fullScreen() {
  const enter = vi.fn().mockResolvedValue(undefined);
  document.documentElement.requestFullscreen = enter;
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  return enter;
}

it("starts a dispatch with 3 claim agents at once, full screen in the live view", async () => {
  const fetchMock = stubBackend({
    "/api/claims": queue,
    "POST /api/dispatches": { accepted: true },
    "/api/runs/current": null,
    "/api/runs/running": null,
  });
  const enter = fullScreen();
  render(<App />);
  const agents = await screen.findByRole("spinbutton", {
    name: "Claim agents at once",
  });
  expect((agents as HTMLInputElement).value).toBe("3");
  fireEvent.click(screen.getByRole("button", { name: "Start a dispatch" }));
  expect(enter).toHaveBeenCalled();
  await waitFor(() => {
    expect(window.location.hash).toBe("#/live");
  });
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(post?.[0]).toBe("/api/dispatches");
  expect(post?.[1]?.body).toBe(JSON.stringify({ n: 3 }));
});

it.each([
  ["7", "7"],
  ["0", "1"],
  ["40", "25"],
])(
  "holds the claim agents at once between 1 and 25: %s",
  async (typed, held) => {
    stubBackend({ "/api/claims": queue });
    render(<App />);
    const agents = await screen.findByRole("spinbutton", {
      name: "Claim agents at once",
    });
    fireEvent.change(agents, { target: { value: typed } });
    expect((agents as HTMLInputElement).value).toBe(held);
  },
);

it("passes the chosen N to the dispatch", async () => {
  const fetchMock = stubBackend({
    "/api/claims": queue,
    "POST /api/dispatches": { accepted: true },
  });
  fullScreen();
  render(<App />);
  const agents = await screen.findByRole("spinbutton", {
    name: "Claim agents at once",
  });
  fireEvent.change(agents, { target: { value: "25" } });
  fireEvent.click(screen.getByRole("button", { name: "Start a dispatch" }));
  await waitFor(() => {
    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(post?.[1]?.body).toBe(JSON.stringify({ n: 25 }));
  });
});

it("says when the agent's service isn't running", async () => {
  stubBackend({ "/api/claims": queue });
  const backend = globalThis.fetch;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
    init?.method === "POST"
      ? Promise.resolve(
          new Response(
            JSON.stringify({ detail: "The agent's service isn't running" }),
            { status: 503 },
          ),
        )
      : backend(input, init),
  );
  fullScreen();
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Start a dispatch" }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The agent's service isn't running",
  );
  expect(window.location.hash).toBe("");
});

it("won't start a dispatch while a dispatch or evaluation is running", async () => {
  stubBackend({
    "/api/claims": queue,
    "/api/runs/running": runRecord({ kind: "evaluation" }),
  });
  render(<App />);
  expect(
    await screen.findByText("A dispatch or evaluation is already running"),
  ).toBeDefined();
  const button = screen.getByRole("button", { name: "Start a dispatch" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
});

it("shows the dispatch's claims with where each stands, its cost and its time", async () => {
  stubBackend({
    "/api/claims": queue,
    "/api/runs/current": runRecord({
      total: 3,
      claims: [
        runClaim({
          claim_id: "CLM-1003",
          status: "decided",
          decision: "refer",
        }),
        runClaim({ claim_id: "CLM-1001", status: "in_progress" }),
        runClaim({ claim_id: "CLM-1002", status: "waiting" }),
      ],
      cost: 0.0123,
      seconds: 95,
      elapsed: 40,
    }),
  });
  render(<App />);
  const panel = await screen.findByRole("region", {
    name: "The latest dispatch",
  });
  const items = within(panel).getAllByRole("listitem");
  expect(items.map((item) => item.textContent)).toEqual([
    "CLM-1003Decided",
    "CLM-1001In progress",
    "CLM-1002Waiting",
  ]);
  expect(
    within(items[0])
      .getByRole("link", { name: "CLM-1003" })
      .getAttribute("href"),
  ).toBe("#/claims/CLM-1003");
  expect(panel.textContent).toContain(
    "Running · 3 claim agents at once · 1 of 3 claims done",
  );
  expect(panel.textContent).toContain("Model cost$0.0123");
  expect(panel.textContent).toContain("Agent time1m 35s");
  expect(panel.textContent).toContain("Run time40s");
  expect(within(panel).queryByText("Summary")).toBeNull();
});

it("shows the summary from the records once the dispatch ends", async () => {
  stubBackend({
    "/api/claims": queue,
    "/api/runs/current": runRecord({
      status: "finished",
      summary: {
        approved: 2,
        declined: 1,
        referred: 1,
        awaiting_sign_off: [
          { claim_id: "CLM-1008", payout: 2240 },
          { claim_id: "CLM-1011", payout: 1150 },
        ],
        left_for_handler: ["CLM-1004"],
        in_progress: ["CLM-1005"],
      },
    }),
  });
  render(<App />);
  const panel = await screen.findByRole("region", {
    name: "The latest dispatch",
  });
  const summary = within(panel).getByText("Summary").parentElement;
  expect(summary?.textContent).toContain(
    "2 approved, 1 declined and 1 referred.",
  );
  expect(summary?.textContent).toContain(
    "Waiting for a sign-off: CLM-1008 $2,240.00, CLM-1011 $1,150.00",
  );
  expect(summary?.textContent).toContain("Left for a handler: CLM-1004");
  expect(summary?.textContent).toContain("Still in progress: CLM-1005");
  expect(panel.textContent).toContain("Finished");
});
