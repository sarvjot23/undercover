import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Evaluation, EvaluationSummary, Run, Scores } from "./api";
import { App } from "./App";
import { runClaim, runRecord, stubBackend } from "./testing";

vi.mock("./auth");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

const scores: Scores = {
  decision_accuracy: 0.8,
  accuracy: 0.6,
  cost_of_mistakes: 110,
  straight_through: 0.6,
  cost: 0.05,
  cost_per_claim: 0.01,
  seconds_per_claim: 42,
  seconds: 61,
};

function evaluationSummary(
  overrides: Partial<EvaluationSummary> = {},
): EvaluationSummary {
  const run: Partial<Run> = runRecord({
    kind: "evaluation",
    set_name: "evaluation",
    tiny: true,
    n: 5,
    status: "finished",
  });
  delete run.claims;
  return { ...(run as Omit<Run, "claims">), scores, ...overrides };
}

it("lists the evaluations, newest first, with every measure", async () => {
  window.location.hash = "#/scoreboard";
  stubBackend({
    "/api/evaluations": [
      evaluationSummary({ run_id: 9 }),
      evaluationSummary({
        run_id: 7,
        set_name: "held_out",
        tiny: false,
        n: 25,
        status: "stopped",
        scores: null,
      }),
    ],
    "/api/runs/running": null,
  });
  render(<App />);
  const rows = await screen.findAllByRole("row");
  expect(rows).toHaveLength(3);
  expect(
    within(rows[1])
      .getByRole("link", { name: "Evaluation 9" })
      .getAttribute("href"),
  ).toBe("#/scoreboard/9");
  expect(
    within(rows[1])
      .getAllByRole("cell")
      .map((cell) => cell.textContent),
  ).toEqual([
    "Evaluation 9",
    "Evaluation set",
    "Five tiny claims",
    "5",
    "openai/gpt-6-luna (low)",
    "Finished",
    "80%",
    "60%",
    "$110.00",
    "60%",
    "$0.01",
    "42s",
    "1m 01s",
  ]);
  const stopped = within(rows[2])
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
  expect(stopped.slice(0, 6)).toEqual([
    "Evaluation 7",
    "Held-out set",
    "The whole set",
    "25",
    "openai/gpt-6-luna (low)",
    "Stopped",
  ]);
  expect(stopped.slice(6).every((cell) => cell === "")).toBe(true);
  expect(
    screen
      .getByRole("link", { name: "Scoreboard" })
      .getAttribute("aria-current"),
  ).toBe("page");
});

it("starts an evaluation with its set, its tiny claims and N", async () => {
  window.location.hash = "#/scoreboard";
  const fetchMock = stubBackend({
    "/api/evaluations": [],
    "POST /api/evaluations": { accepted: true },
  });
  render(<App />);
  expect(await screen.findByText("No evaluations yet.")).toBeDefined();
  fireEvent.change(screen.getByRole("combobox", { name: "Labelled set" }), {
    target: { value: "held_out" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Claims" }), {
    target: { value: "tiny" },
  });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "Claim agents at once" }),
    { target: { value: "5" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Start an evaluation" }));
  await waitFor(() => {
    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(post?.[1]?.body).toBe(
      JSON.stringify({ set_name: "held_out", tiny: true, n: 5 }),
    );
  });
});

it("won't start an evaluation while a run is going", async () => {
  window.location.hash = "#/scoreboard";
  stubBackend({ "/api/evaluations": [], "/api/runs/running": runRecord() });
  render(<App />);
  expect(
    await screen.findByText("A dispatch or evaluation is already running"),
  ).toBeDefined();
  const button = screen.getByRole("button", { name: "Start an evaluation" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
});

const evaluation: Evaluation = {
  ...runRecord({
    run_id: 7,
    kind: "evaluation",
    set_name: "evaluation",
    tiny: true,
    n: 5,
    status: "finished",
  }),
  scores,
  claims: [
    {
      ...runClaim({
        claim_id: "EV7-CLM-1007",
        source_id: "CLM-1007",
        status: "decided",
        decision: "approve",
        payout: 50,
        cost: 0.012,
        seconds: 30,
      }),
      handler_decision: "approve",
      handler_payout: 50,
      agent_decision: "approve",
      agent_payout: 50,
      right: true,
      mistake_cost: 0,
    },
    {
      ...runClaim({
        claim_id: "EV7-CLM-1020",
        source_id: "CLM-1020",
        status: "decided",
        decision: "approve",
        payout: 300,
      }),
      handler_decision: "approve",
      handler_payout: 240,
      agent_decision: "approve",
      agent_payout: 300,
      right: false,
      mistake_cost: 60,
    },
    {
      ...runClaim({
        claim_id: "EV7-CLM-1021",
        source_id: "CLM-1021",
        status: "in_progress",
      }),
      handler_decision: "approve",
      handler_payout: 825,
      agent_decision: "refer",
      agent_payout: 0,
      right: false,
      mistake_cost: 50,
    },
  ],
};

it("shows an evaluation's claims, the handler's answer beside the agent's", async () => {
  window.location.hash = "#/scoreboard/7";
  stubBackend({ "/api/evaluations/7": evaluation });
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Evaluation 7" }),
  ).toBeDefined();
  const rows = screen.getAllByRole("row").slice(1);
  expect(
    rows.map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ),
  ).toEqual([
    [
      "EV7-CLM-1007",
      "CLM-1007",
      "Approved $50.00",
      "Approved $50.00",
      "Right",
      "",
      "$0.012",
      "30s",
    ],
    [
      "EV7-CLM-1020",
      "CLM-1020",
      "Approved $240.00",
      "Approved $300.00",
      "Miss",
      "$60.00",
      "$0.00",
      "0s",
    ],
    [
      "EV7-CLM-1021",
      "CLM-1021",
      "Approved $825.00",
      "Not decided, counted as a referral",
      "Miss",
      "$50.00",
      "$0.00",
      "0s",
    ],
  ]);
  expect(rows.map((row) => row.className)).toEqual(["", "miss", "miss"]);
  expect(
    within(rows[0])
      .getByRole("link", { name: "EV7-CLM-1007" })
      .getAttribute("href"),
  ).toBe("#/claims/EV7-CLM-1007");
  expect(screen.getByText(/claims missed/).textContent).toBe(
    "2 of 3 claims missed",
  );
  expect(screen.getByText("Decision accuracy").nextSibling?.textContent).toBe(
    "80%",
  );
});

it("says when an evaluation stopped partway", async () => {
  window.location.hash = "#/scoreboard/7";
  stubBackend({
    "/api/evaluations/7": { ...evaluation, status: "stopped", scores: null },
  });
  render(<App />);
  expect((await screen.findByRole("status")).textContent).toContain(
    "Stopped partway, so it has no measures",
  );
  expect(screen.queryByText("Decision accuracy")).toBeNull();
});

it("says when there's no such evaluation", async () => {
  window.location.hash = "#/scoreboard/99";
  stubBackend({});
  render(<App />);
  expect((await screen.findByRole("alert")).textContent).toBe(
    "There is no evaluation 99.",
  );
});
