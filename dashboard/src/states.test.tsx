import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { dana, pathOf, stubBackend, summary } from "./testing";

vi.mock("./auth");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.location.hash = "";
});

const PAGES: [string, string][] = [
  ["#/", "Loading the queue"],
  ["#/claims/CLM-1001", "Loading the claim"],
  ["#/scoreboard", "Loading the scoreboard"],
  ["#/scoreboard/4", "Loading the evaluation"],
  ["#/improvement", "Loading the rounds"],
  ["#/configuration", "Loading the configuration"],
  ["#/settings", "Loading the settings"],
];

it.each(PAGES)("%s keeps space for what is loading", async (hash, text) => {
  window.location.hash = hash;
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => undefined)),
  );
  render(<App />);
  const loading = await screen.findByText(text);
  expect(loading.getAttribute("role")).toBe("status");
  expect(loading.className).toContain("state-loading");
});

it.each(PAGES)("%s says what went wrong and what to do", async (hash) => {
  window.location.hash = hash;
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<App />);
  const alert = await screen.findByRole("alert");
  expect(alert.closest(".state-error")).not.toBeNull();
  expect(alert.nextElementSibling?.textContent).not.toBe("");
});

it("tries again after an error", async () => {
  window.location.hash = "#/";
  const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  const retry = await screen.findByRole("button", { name: "Try again" });
  stubBackend({ "/api/claims": [summary()], "/api/handlers": [dana] });
  fireEvent.click(retry);
  expect(await screen.findByRole("link", { name: "CLM-1001" })).toBeDefined();
});

const EMPTY: [string, Record<string, unknown>, string][] = [
  ["#/", { "/api/claims": [] }, "The queue is empty."],
  ["#/scoreboard", { "/api/evaluations": [] }, "No evaluations yet."],
  ["#/improvement", { "/api/rounds": [] }, "No rounds yet."],
];

it.each(EMPTY)(
  "%s says when there is nothing yet",
  async (hash, routes, text) => {
    window.location.hash = hash;
    stubBackend(routes);
    render(<App />);
    const title = await screen.findByText(text);
    expect(title.closest(".state-empty")).not.toBeNull();
    expect(title.nextElementSibling?.textContent).not.toBe("");
  },
);

it("keeps the page as it is while it refreshes", async () => {
  window.location.hash = "#/";
  const fetchMock = stubBackend({
    "/api/claims": [summary()],
    "/api/handlers": [dana],
  });
  render(<App />);
  await screen.findByRole("link", { name: "CLM-1001" });
  const loads = () =>
    fetchMock.mock.calls.filter(([input]) => pathOf(input) === "/api/claims")
      .length;
  const before = loads();
  fetchMock.mockImplementation(() => new Promise(() => undefined));
  await waitFor(
    () => {
      expect(loads()).toBeGreaterThan(before);
    },
    { timeout: 4000 },
  );
  expect(screen.getByRole("link", { name: "CLM-1001" })).toBeDefined();
  expect(screen.queryByText("Loading the queue")).toBeNull();
});
