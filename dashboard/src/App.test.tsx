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
import { stubBackend, summary } from "./testing";

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
    "/api/instructions": { text: "You are the UnderCover Agent." },
  });
  render(<App />);
  expect(
    await screen.findByText("You are the UnderCover Agent."),
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
    "POST /api/queue/run": { running: true },
    "/api/queue/run": { running: true },
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
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    true,
  );
  expect(
    await screen.findByRole("button", { name: "Leave (Esc)" }),
  ).toBeDefined();
});

it("leaves the live view and full screen", async () => {
  window.location.hash = "#/live";
  stubBackend({ "/api/claims": queue, "/api/queue/run": { running: false } });
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
