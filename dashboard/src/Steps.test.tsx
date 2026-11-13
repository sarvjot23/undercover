import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { Step } from "./api";
import { Steps } from "./Steps";

afterEach(cleanup);

const plans = {
  file: "plans.yaml",
  system: "Policy administration",
  owner: "Products",
  reviewed: "2026-09-01",
};

const steps: Step[] = [
  {
    step_id: 1,
    kind: "check",
    text: "No instructions found",
    at: "",
    detail: null,
  },
  {
    step_id: 2,
    kind: "tool_call",
    text: 'undercover-context___get_plan {"plan": "premium"}',
    at: "",
    detail: null,
  },
  {
    step_id: 3,
    kind: "lookup",
    text: "The premium plan",
    at: "",
    detail: { looked_up: "The premium plan", files: [plans] },
  },
  {
    step_id: 4,
    kind: "lookup",
    text: "The documents, for “zeppelin”",
    at: "",
    detail: { looked_up: "The documents, for “zeppelin”", files: [] },
  },
  {
    step_id: 5,
    kind: "memory_search",
    text: "Searched memory for 'passport': A first claim, approved.",
    at: "",
    detail: { query: "passport" },
  },
  {
    step_id: 6,
    kind: "refusal",
    text: "undercover-app___calculate_payout: Refused by the Gateway: Tool Execution Denied",
    at: "",
    detail: { by: "the Gateway" },
  },
  {
    step_id: 7,
    kind: "refusal",
    text: "record_decision: Refused by the app: Claims manual section 14: an approval needs the payout calculation for this attempt",
    at: "",
    detail: { by: "the app" },
  },
  {
    step_id: 8,
    kind: "tool_call",
    text: "record_decision {}",
    at: "",
    detail: null,
  },
  {
    step_id: 9,
    kind: "tool_result",
    text: "record_decision: {}",
    at: "",
    detail: null,
  },
  {
    step_id: 10,
    kind: "memory_save",
    text: "Claim CLM-1005: Passport eaten by a giraffe at breakfast.",
    at: "",
    detail: null,
  },
  { step_id: 11, kind: "error", text: "Timed out", at: "", detail: null },
  {
    step_id: 12,
    kind: "answer",
    text: "CLM-1005: approve $150.00",
    at: "",
    detail: null,
  },
];

function rows() {
  return Array.from(document.querySelectorAll(".step")).map((row) => ({
    kind: row.querySelector(".step-kind")?.textContent,
    text: row.querySelector(".step-text")?.textContent,
    source: row.querySelector(".step-source")?.textContent,
  }));
}

it("shows each kind of step in plain words", () => {
  render(<Steps steps={steps} />);
  expect(rows().map((row) => row.kind)).toEqual([
    "Security check",
    "Calls",
    "Looked up",
    "Looked up",
    "Searched memory",
    "Refused by the Gateway",
    "Refused by the app",
    "Calls",
    "Result",
    "Saved to memory",
    "Error",
    "Answer",
  ]);
});

it("says where each lookup came from", () => {
  render(<Steps steps={steps} />);
  expect(rows()[2]?.source).toBe("From plans.yaml (Policy administration)");
  expect(rows()[3]?.source).toBe("Nothing found");
  expect(rows()[1]?.source).toBeUndefined();
});

it("makes a refusal stand out, labeled by who refused", () => {
  render(<Steps steps={steps} />);
  const gateway = screen.getByText("Refused by the Gateway").closest("li");
  expect(gateway?.className).toContain("step-refusal");
  expect(rows()[5]?.text).toBe(
    "undercover-app___calculate_payout: Tool Execution Denied",
  );
  expect(rows()[6]?.text).toBe(
    "record_decision: Claims manual section 14: an approval needs the payout calculation for this attempt",
  );
  // The agent's next attempt at the record follows the section 14 refusal.
  expect(rows()[7]?.text).toBe("record_decision {}");
});

it("shows a handler's note on a decision sent back, with who sent it", () => {
  render(
    <Steps
      steps={[
        {
          step_id: 20,
          kind: "send_back",
          text: "The carrier already paid $350.",
          at: "",
          detail: { by: "Dana Whitfield" },
        },
      ]}
    />,
  );
  expect(rows()).toEqual([
    {
      kind: "Sent back by Dana Whitfield",
      text: "The carrier already paid $350.",
      source: undefined,
    },
  ]);
});
