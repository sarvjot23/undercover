import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Round, SettingsRecord } from "./api";
import { App } from "./App";
import { chartPoints } from "./rounds";
import { dana, marcus, pathOf, signInAs, stubBackend } from "./testing";

vi.mock("./auth");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
  signInAs(dana.email);
});

const settings: SettingsRecord["settings"] = {
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
};

function round(overrides: Partial<Round> = {}): Round {
  return {
    round_id: 1,
    stop_reason: null,
    thread_id: "round-1-abc",
    recipe_version: 1,
    settings,
    status: "working",
    stage: "first_evaluations",
    progress: null,
    proposal: null,
    version_before: 1,
    version_tried: null,
    reason: null,
    before: null,
    after: null,
    verdict: null,
    why: null,
    started_by: "HND-01",
    started_at: "2026-11-04T10:00:00+00:00",
    finished_at: null,
    tried: null,
    events: [],
    evaluations: [],
    spent: 0.0123,
    ...overrides,
  };
}

const change = round({
  status: "waiting",
  stage: "change_waiting",
  proposal: {
    kind: "change",
    instructions: "Refer a claim with a document missing.",
    model: "openai/gpt-6-luna",
    reasoning: "medium",
    reason: "Three misses had a document missing.",
    diff: [
      { kind: "same", text: "You are the UnderCover Agent." },
      { kind: "add", text: "Refer a claim with a document missing." },
    ],
    model_before: "openai/gpt-6-luna",
    reasoning_before: "low",
  },
});

const finished = round({
  round_id: 1,
  status: "finished",
  stage: "finished",
  version_tried: 2,
  tried: { version: 2, model: "openai/gpt-6-luna", reasoning: "medium" },
  reason: "Three misses had a document missing.",
  before: { runs: 2, accuracy: 0.8, grade: 1.5 },
  after: { runs: 2, accuracy: 0.88, grade: 1.9 },
  verdict: "kept",
  why: "the grade improved by more than the noise",
  events: [
    {
      event_id: 1,
      decision: "reject",
      proposal: "change",
      handler_id: "HND-01",
      message: "Too broad.",
      at: "2026-11-04T10:05:00+00:00",
    },
    {
      event_id: 2,
      decision: "approve",
      proposal: "change",
      handler_id: "HND-01",
      message: "",
      at: "2026-11-04T10:06:00+00:00",
    },
  ],
  spent: 0.21,
});

function open(rounds: Round[], extra: Record<string, unknown> = {}) {
  window.location.hash = "#/improvement";
  return stubBackend({
    "/api/rounds": rounds,
    "/api/handlers": [dana, marcus],
    "/api/recipes": [
      {
        version: 2,
        recipe: "1. Read.\n2. Propose one rule.",
        reason: "Smaller changes.",
        proposed_by: "improver",
        approved_by: "HND-01",
        approved_at: "2026-11-04T10:09:00+00:00",
      },
      {
        version: 1,
        recipe: "1. Read.",
        reason: "The first recipe.",
        proposed_by: "seed",
        approved_by: null,
        approved_at: "2026-11-04T09:00:00+00:00",
      },
    ],
    "/api/recipes/2/diff": {
      version: 2,
      before: 1,
      recipe: [
        { kind: "same", text: "1. Read." },
        { kind: "add", text: "2. Propose one rule." },
      ],
    },
    "/api/recipes/1/diff": {
      version: 1,
      before: null,
      recipe: [{ kind: "add", text: "1. Read." }],
    },
    ...extra,
  });
}

const STAGE_SHOWN: [Partial<Round>, string][] = [
  [
    { stage: "first_evaluations", progress: "2 of 3" },
    "First evaluations 2 of 3",
  ],
  [{ stage: "improving" }, "The improver at work"],
  [
    { stage: "change_waiting", status: "waiting" },
    "A change waiting for approval",
  ],
  [{ stage: "evaluations", progress: "1 of 3" }, "Evaluations 1 of 3"],
  [
    { stage: "verdict", verdict: "rolled_back", why: "no score improved" },
    "The verdict",
  ],
  [
    { stage: "improving", verdict: "kept", why: "accuracy improved" },
    "The verdict",
  ],
  [
    { stage: "recipe_waiting", status: "waiting" },
    "A recipe waiting for approval",
  ],
];

it.each(STAGE_SHOWN)(
  "shows where a round has got to: %o",
  async (stage, shown) => {
    open([round(stage)]);
    render(<App />);
    const steps = await screen.findByRole("list", {
      name: "Where the round has got to",
    });
    const current = within(steps)
      .getAllByRole("listitem")
      .find((step) => step.getAttribute("aria-current") === "step");
    expect(current?.textContent).toBe(shown);
  },
);

it("shows a proposal's diff with the model and effort before and after", async () => {
  open([change]);
  render(<App />);
  const proposal = await screen.findByRole("region", {
    name: "A change to the claim agent, waiting for approval",
  });
  expect(
    within(proposal).getByText("Three misses had a document missing."),
  ).toBeDefined();
  expect(within(proposal).getByText("low").tagName).toBe("DEL");
  expect(within(proposal).getByText("medium").tagName).toBe("INS");
  const added = within(proposal).getByText(
    "Refer a claim with a document missing.",
    {
      selector: ".diff-text",
    },
  );
  expect(added.closest("ins")).not.toBeNull();
});

it("approves a proposal after a confirmation", async () => {
  const fetchMock = open([change], {
    "POST /api/rounds/1/decision": { accepted: true },
  });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  const dialog = screen.getByRole("dialog", { name: "Approve this change?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
  await waitFor(() => {
    const sent = fetchMock.mock.calls.find(
      ([input]) => pathOf(input) === "/api/rounds/1/decision",
    );
    expect(JSON.parse(sent?.[1]?.body as string)).toEqual({
      decision: "approve",
      message: "",
    });
  });
});

it("rejects a proposal only with a reason", async () => {
  const fetchMock = open([change], {
    "POST /api/rounds/1/decision": { accepted: true },
  });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
  const dialog = screen.getByRole("dialog", { name: "Reject this change?" });
  const confirm = within(dialog).getByRole("button", { name: "Reject" });
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(dialog).getByRole("textbox"), {
    target: { value: "Too broad: it names a claim." },
  });
  fireEvent.click(confirm);
  await waitFor(() => {
    const sent = fetchMock.mock.calls.find(
      ([input]) => pathOf(input) === "/api/rounds/1/decision",
    );
    expect(JSON.parse(sent?.[1]?.body as string)).toEqual({
      decision: "reject",
      message: "Too broad: it names a claim.",
    });
  });
});

it("says why a decision was refused", async () => {
  open([change]);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The backend refused it.",
  );
});

it("lists the rounds newest first with their scores, verdicts and approvals", async () => {
  open([
    round({
      round_id: 2,
      status: "stopped",
      stage: "stopped",
      stop_reason: "The agent stopped answering",
    }),
    finished,
  ]);
  render(<App />);
  const table = await screen.findByRole("table", { name: "Rounds" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows[0]?.textContent).toContain("Stopped");
  expect(rows[0]?.textContent).toContain("The agent stopped answering");
  const done = rows[1]?.textContent ?? "";
  expect(done).toContain("Version 2");
  expect(done).toContain("80% to 88%");
  expect(done).toContain("1.50 to 1.90");
  expect(done).toContain("Kept");
  expect(done).toContain("the grade improved by more than the noise");
  expect(done).toContain("Rejected the change: Dana Whitfield");
  expect(done).toContain("“Too broad.”");
  expect(done).toContain("$0.21");
});

it("plots each version tried on the held-out set", async () => {
  open([finished]);
  render(<App />);
  const accuracy = await screen.findByRole("img", {
    name: /^Held-out accuracy/,
  });
  const points = accuracy.querySelectorAll("circle");
  expect(
    [...points].map((point) => point.getAttribute("data-version")),
  ).toEqual(["1", "2"]);
  expect(points[1].textContent).toBe("Version 2: 88%, kept");
  expect(accuracy.getAttribute("aria-label")).toBe(
    "Held-out accuracy by version: version 1 80%, version 2 88%",
  );
  expect(chartPoints([round()])).toEqual([]);
});

it("says when no version has been tried and no round has run", async () => {
  open([]);
  render(<App />);
  expect(await screen.findByText(/No rounds yet/)).toBeDefined();
  expect(screen.getByText(/No version has been tried yet/)).toBeDefined();
});

it("shows the recipe's versions with the same diff view", async () => {
  open([]);
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Recipe 2 against recipe 1" }),
  ).toBeDefined();
  expect(
    screen.getByText("2. Propose one rule.").closest("ins"),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Recipe 1" }));
  expect(
    await screen.findByRole("heading", { name: "Recipe 1, the first" }),
  ).toBeDefined();
});

it("starts and stops a round after a confirmation", async () => {
  const fetchMock = open([], { "POST /api/rounds": { accepted: true } });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Start a round" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Start a round",
    }),
  );
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          pathOf(input) === "/api/rounds" && init?.method === "POST",
      ),
    ).toBe(true);
  });
  cleanup();

  const stopping = open([round()], { "POST /api/rounds/1/stop": round() });
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Stop the round" }),
  );
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Stop the round",
    }),
  );
  await waitFor(() => {
    expect(
      stopping.mock.calls.some(
        ([input]) => pathOf(input) === "/api/rounds/1/stop",
      ),
    ).toBe(true);
  });
});

it("shows Marcus why he can't start, stop, approve or reject", async () => {
  signInAs(marcus.email);
  open([change]);
  render(<App />);
  expect(
    await screen.findByText(
      "Only a handler who can sign off payouts over the limit can start or stop a round, or approve or reject the improver’s proposals.",
    ),
  ).toBeDefined();
  expect(
    screen.getByText(
      "Only a handler who can sign off payouts over the limit can approve or reject the improver’s proposals.",
    ),
  ).toBeDefined();
  for (const name of ["Start a round", "Stop the round", "Approve", "Reject"]) {
    expect(screen.queryByRole("button", { name })).toBeNull();
  }
});
