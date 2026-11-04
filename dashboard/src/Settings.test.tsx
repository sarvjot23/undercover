import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { SettingsRecord } from "./api";
import { App } from "./App";
import { dana, marcus, pathOf, signInAs, stubBackend } from "./testing";

vi.mock("./auth");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  signInAs(dana.email);
});

const record: SettingsRecord = {
  settings: {
    approval_limit: 800,
    objectives: { accuracy: 0.6, grade: 1 },
    noise: {
      accuracy: 0.1,
      grade: 0.15,
      cost_per_claim: 0.15,
      seconds_per_claim: 0.15,
    },
    tolerance: {
      accuracy: 0.1,
      grade: 0.15,
      cost_per_claim: 1,
      seconds_per_claim: 0.25,
    },
    round_spending_limit: 0.5,
    agents_at_once: 25,
  },
  changes: [
    {
      change_id: 1,
      name: "agents_at_once",
      before: 20,
      after: 25,
      handler_id: "HND-01",
      changed_at: "2026-11-04T10:00:00+00:00",
    },
  ],
  models: [
    {
      model: "openai/gpt-6-luna",
      reasoning_efforts: ["none", "low", "medium"],
      input_price: 0.1,
      output_price: 0.5,
    },
  ],
};

function open() {
  window.location.hash = "#/settings";
  return stubBackend({
    "/api/settings": record,
    "/api/handlers": [dana, marcus],
  });
}

it("lets Dana change a setting after a confirmation", async () => {
  const fetchMock = open();
  render(<App />);
  const limit = await screen.findByRole("spinbutton", {
    name: /Approval limit/,
  });
  expect((limit as HTMLInputElement).value).toBe("800");
  const accuracy = screen.getAllByRole("spinbutton", { name: /Accuracy/ })[0];
  expect((accuracy as HTMLInputElement).value).toBe("10");

  fireEvent.change(limit, { target: { value: "1000" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  const dialog = screen.getByRole("dialog", { name: "Change the settings?" });
  expect(within(dialog).getByText("$800.00")).toBeDefined();
  expect(within(dialog).getByText("$1,000.00")).toBeDefined();
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(
    false,
  );

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Change the settings" }),
  );
  await waitFor(() => {
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    if (!put) throw new Error("Nothing was sent yet");
    expect(pathOf(put[0])).toBe("/api/settings");
    expect(JSON.parse(put[1]?.body as string)).toMatchObject({
      approval_limit: 1000,
      noise: { accuracy: 0.1 },
    });
  });
});

it("cancels a change in the dialog with nothing sent", async () => {
  const fetchMock = open();
  render(<App />);
  const agents = await screen.findByRole("spinbutton", {
    name: /Claim agents at once/,
  });
  fireEvent.change(agents, { target: { value: "10" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect((agents as HTMLInputElement).value).toBe("25");
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(
    false,
  );
});

it("shows Marcus the settings read only, and why", async () => {
  signInAs(marcus.email);
  open();
  render(<App />);
  expect(
    await screen.findByText(
      "Only a handler who can sign off payouts over the limit can change the settings.",
    ),
  ).toBeDefined();
  expect(screen.queryByRole("spinbutton")).toBeNull();
  expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
  expect(screen.getByText("Payouts: Approval limit")).toBeDefined();
});

it("lists the changes and the models allowed", async () => {
  open();
  render(<App />);
  const changes = await screen.findByRole("region", { name: "Changes" });
  expect(within(changes).getByText("Dana Whitfield")).toBeDefined();
  expect(
    within(changes).getByText("Rounds of improvement, Claim agents at once"),
  ).toBeDefined();
  const models = screen.getByRole("region", { name: "The models allowed" });
  expect(within(models).getByText("none, low, medium")).toBeDefined();
  expect(within(models).getByText("$0.50")).toBeDefined();
});

it("switches the theme and remembers it", async () => {
  open();
  render(<App />);
  fireEvent.click(await screen.findByRole("radio", { name: "Dark" }));
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  expect(localStorage.getItem("undercover-theme")).toBe("dark");
  fireEvent.click(
    screen.getByRole("radio", { name: "The same as the computer" }),
  );
  expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  cleanup();
  localStorage.setItem("undercover-theme", "light");
  render(<App />);
  expect(
    (await screen.findByRole<HTMLInputElement>("radio", { name: "Light" }))
      .checked,
  ).toBe(true);
});
