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
import { runRecord, stubBackend, summary } from "./testing";

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
    "/api/instructions": {
      queue: "You run the claims queue.",
      claim: "You decide one claim.",
    },
  });
  render(<App />);
  expect(await screen.findByText("You run the claims queue.")).toBeDefined();
  expect(screen.getByText("You decide one claim.")).toBeDefined();
  expect(
    screen.getByRole("heading", { name: "Working the queue" }),
  ).toBeDefined();
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

it("runs the queue full screen in the live view", async () => {
  const fetchMock = stubBackend({
    "/api/claims": queue,
    "POST /api/runs": runRecord({ total: 2 }),
    "/api/runs/current": runRecord({ status: "finished", active: false }),
  });
  const fullscreen = vi.fn().mockResolvedValue(undefined);
  document.documentElement.requestFullscreen = fullscreen;
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Run the queue" }));
  expect(fullscreen).toHaveBeenCalled();
  await waitFor(() => {
    expect(window.location.hash).toBe("#/live");
  });
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(post?.[0]).toBe("/api/runs");
  expect(post?.[1]?.body).toBe(JSON.stringify({ cap: 1 }));
  expect(
    await screen.findByRole("button", { name: "Leave (Esc)" }),
  ).toBeDefined();
});

it("leaves the live view and full screen", async () => {
  window.location.hash = "#/live";
  stubBackend({
    "/api/claims": queue,
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

it("starts a trial run on the number of claims chosen", async () => {
  const many = ["CLM-1001", "CLM-1002", "CLM-1003", "CLM-1004"].map((claimId) =>
    summary({ claim_id: claimId }),
  );
  const fetchMock = stubBackend({
    "/api/claims": many,
    "POST /api/runs": runRecord({ total: 2, cap: 2 }),
  });
  document.documentElement.requestFullscreen = vi
    .fn()
    .mockResolvedValue(undefined);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  render(<App />);
  const cap = await screen.findByRole("spinbutton", {
    name: "Claims in this run",
  });
  expect((cap as HTMLInputElement).value).toBe("4");
  fireEvent.change(cap, { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Run the queue" }));
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(post?.[1]?.body).toBe(JSON.stringify({ cap: 2 }));
});

it("shows the agent's to-do list, ticked off as it goes", async () => {
  stubBackend({
    "/api/claims": queue,
    "/api/runs/current": runRecord({
      total: 3,
      claim_ids: ["CLM-1003", "CLM-1001"],
      todos: [
        { claim_id: "CLM-1003", note: "Passport, $243", status: "done" },
        { claim_id: "CLM-1001", note: "Trip delay", status: "in_progress" },
        { claim_id: "CLM-1002", note: "Baggage", status: "to_do" },
      ],
    }),
  });
  render(<App />);
  const list = await screen.findByRole("region", {
    name: "The agent’s to-do list",
  });
  const items = within(list).getAllByRole("listitem");
  expect(items.map((item) => item.textContent)).toEqual([
    "CLM-1003Passport, $243Done",
    "CLM-1001Trip delayIn progress",
    "CLM-1002BaggageTo do",
  ]);
  expect(list.textContent).toContain("2 of 3 claims taken");
});

it("shows the agent's summary when the run ends", async () => {
  stubBackend({
    "/api/claims": queue,
    "/api/runs/current": runRecord({
      status: "finished",
      summary: "Two approved, one left for a handler.",
      todos: [
        {
          claim_id: "CLM-1002",
          note: "Baggage",
          status: "left_for_handler",
        },
      ],
    }),
  });
  render(<App />);
  expect(
    await screen.findByText("Two approved, one left for a handler."),
  ).toBeDefined();
  expect(screen.getByText("The agent's summary")).toBeDefined();
  expect(screen.getAllByText("Left for a handler").length).toBeGreaterThan(0);
});

it("says the agent is planning before the list is written", async () => {
  stubBackend({ "/api/claims": queue, "/api/runs/current": runRecord() });
  render(<App />);
  expect(
    await screen.findByText("The agent is planning the run."),
  ).toBeDefined();
});

it("won't start a second run while one is in progress", async () => {
  stubBackend({
    "/api/claims": queue,
    "/api/runs/current": runRecord({ active: true }),
  });
  render(<App />);
  expect(await screen.findByText("A run is already in progress")).toBeDefined();
  const button = screen.getByRole("button", { name: "Run the queue" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
});

it("offers to finish a run that stopped partway", async () => {
  const fetchMock = stubBackend({
    "/api/claims": queue,
    "/api/runs/current": runRecord({ active: false, cap: 3 }),
    "POST /api/runs": runRecord({ active: true, cap: 3 }),
  });
  document.documentElement.requestFullscreen = vi
    .fn()
    .mockResolvedValue(undefined);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  render(<App />);
  expect(
    await screen.findByText(
      "The last run stopped partway. Running the queue finishes it",
    ),
  ).toBeDefined();
  const button = screen.getByRole("button", { name: "Run the queue" });
  expect((button as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(button);
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(true);
  });
});

it("lets a new run start after the last one finished", async () => {
  stubBackend({
    "/api/claims": queue,
    "/api/runs/current": runRecord({ status: "finished", active: false }),
  });
  render(<App />);
  await screen.findByRole("region", { name: "The agent’s to-do list" });
  const button = screen.getByRole("button", { name: "Run the queue" });
  expect((button as HTMLButtonElement).disabled).toBe(false);
  expect(screen.queryByText("A run is already in progress")).toBeNull();
});
