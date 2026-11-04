import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ConfigVersion, VersionDiff } from "./api";
import { App } from "./App";
import { dana, stubBackend } from "./testing";

vi.mock("./auth");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

function version(overrides: Partial<ConfigVersion> = {}): ConfigVersion {
  return {
    version: 1,
    instructions: "You are the UnderCover Agent.",
    model: "openai/gpt-6-luna",
    reasoning: "low",
    reason: "The claim agent as it was before the improver.",
    proposed_by: "seed",
    approved_by: null,
    approved_at: "2026-11-04T10:00:00+00:00",
    current: true,
    changed: [],
    scores: { evaluation: null, held_out: null },
    ...overrides,
  };
}

const versions = [
  version({
    version: 2,
    instructions:
      "You are the UnderCover Agent.\nRefer a claim with no receipt.",
    reasoning: "medium",
    reason: "Two misses had no receipt.",
    proposed_by: "improver",
    approved_by: "HND-01",
    current: true,
    changed: ["instructions", "reasoning effort"],
    scores: {
      evaluation: { runs: 1, accuracy: 0.88 },
      held_out: { runs: 2, accuracy: 0.84, grade: 1.9 },
    },
  }),
  version({ current: false }),
];

const diff: VersionDiff = {
  version: 2,
  before: 1,
  instructions: [
    { kind: "same", text: "You are the UnderCover Agent." },
    { kind: "remove", text: "Decide quickly." },
    { kind: "add", text: "Refer a claim with no receipt." },
  ],
  model: ["openai/gpt-6-luna", "openai/gpt-6-luna"],
  reasoning: ["low", "medium"],
};

it("shows the current version, every version and the diff in color", async () => {
  window.location.hash = "#/instructions";
  stubBackend({
    "/api/configuration/versions": versions,
    "/api/configuration/versions/2/diff": diff,
    "/api/configuration/versions/1/diff": {
      ...diff,
      version: 1,
      before: null,
      instructions: [{ kind: "add", text: "You are the UnderCover Agent." }],
      model: [null, "openai/gpt-6-luna"],
      reasoning: [null, "low"],
    },
    "/api/handlers": [dana],
  });
  render(<App />);
  expect(
    await screen.findByRole("heading", {
      name: "Version 2, the current version",
    }),
  ).toBeDefined();
  expect(
    screen
      .getByRole("link", { name: "Configuration" })
      .getAttribute("aria-current"),
  ).toBe("page");
  const rows = screen.getAllByRole("row");
  expect(rows).toHaveLength(3);
  expect(rows[1]?.textContent).toContain("instructions, reasoning effort");
  expect(rows[1]?.textContent).toContain("The improver");
  expect(rows[1]?.textContent).toContain("84%");
  expect(rows[1]?.textContent).toContain("1.90");
  await waitFor(() => {
    expect(rows[1]?.textContent).toContain("Dana Whitfield");
  });
  expect(rows[2]?.textContent).toContain("None yet");

  const added = await screen.findByText("Refer a claim with no receipt.", {
    selector: ".diff-text",
  });
  expect(added.closest("ins")?.className).toContain("diff-add");
  const removed = screen.getByText("Decide quickly.");
  expect(removed.closest("del")?.className).toContain("diff-remove");
  expect(screen.getByText("low", { selector: "del" })).toBeDefined();
  expect(screen.getByText("medium", { selector: "ins" })).toBeDefined();

  fireEvent.click(
    screen.getAllByRole("button", { name: "Show the changes" })[1],
  );
  expect(
    await screen.findByRole("heading", { name: "Version 1" }),
  ).toBeDefined();
  expect(screen.queryByRole("textbox")).toBeNull();
});

it("says when the configuration can't load", async () => {
  window.location.hash = "#/configuration";
  stubBackend({});
  render(<App />);
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The backend is not responding.",
  );
});
