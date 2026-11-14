import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { freshToken } from "./auth";
import { Copilot } from "./Copilot";
import type { Conversation, CopilotStep, Turn } from "./conversations";
import { linkClaims, turnLine } from "./conversations";
import { dana, marcus, pathOf, stubBackend, summary } from "./testing";

vi.mock("./auth");

const ID = "conv-0123456789abcdef0123456789abcdef";

function step(overrides: Partial<CopilotStep> = {}): CopilotStep {
  return {
    step_id: 1,
    key: "call-1",
    kind: "claims",
    tool: "get_claim",
    input: "CLM-1012",
    state: "done",
    started_at: "2026-11-14T10:00:00+00:00",
    seconds: 1.2,
    asked: '{"claim_id": "CLM-1012"}',
    answer: '{"claim_id": "CLM-1012", "status": "awaiting_sign_off"}',
    reason: "",
    sources: [],
    ...overrides,
  };
}

function turn(overrides: Partial<Turn> = {}): Turn {
  return {
    turn_id: 1,
    message: "What needs me?",
    status: "done",
    started_at: "2026-11-14T10:00:00+00:00",
    answered_at: null,
    ended_at: "2026-11-14T10:00:12+00:00",
    answer: "CLM-1012 needs your sign-off.",
    model_calls: 3,
    cost: 0.0123,
    error: null,
    confirmation: null,
    steps: [step()],
    ...overrides,
  };
}

function conversation(...turns: Turn[]): Conversation {
  return {
    conversation_id: ID,
    title: "What needs me?",
    started_at: "2026-11-14T10:00:00+00:00",
    turns,
  };
}

const LIST = [
  {
    conversation_id: ID,
    handler_id: "HND-01",
    title: "What needs me?",
    started_at: "2026-11-14T10:00:00+00:00",
  },
  {
    conversation_id: "conv-older",
    handler_id: "HND-01",
    title: "Why does CLM-1003 need me?",
    started_at: "2026-11-13T10:00:00+00:00",
  },
];

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

/** The sidebar with this conversation open from the earlier ones. */
async function opened(found: Conversation, handler = dana) {
  const fetchMock = stubBackend({
    "/api/conversations": LIST,
    [`/api/conversations/${ID}`]: found,
    [`POST /api/conversations/${ID}/confirmation`]: found,
  });
  render(<Copilot handler={handler} onCollapse={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Earlier" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "What needs me?" }),
  );
  return fetchMock;
}

it("greets the handler by first name with questions to click", async () => {
  const fetchMock = stubBackend({
    "/api/conversations": [],
    "POST /api/conversations": conversation(
      turn({ status: "working", answer: null, steps: [] }),
    ),
    [`/api/conversations/${ID}`]: conversation(
      turn({ status: "working", answer: null, steps: [] }),
    ),
  });
  render(<Copilot handler={dana} onCollapse={vi.fn()} />);
  expect(screen.getByText("Hello, Dana.")).toBeDefined();
  expect(screen.getByText("Dana Whitfield")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "What needs me today?" }));
  await waitFor(() => {
    expect(freshToken).toHaveBeenCalled();
  });
  const sent = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(sent?.[1]?.body).toBe(
    JSON.stringify({ message: "What needs me today?" }),
  );
  expect(await screen.findByRole("status")).toBeDefined();
});

it("shows the handler's message, the steps and the formatted answer", async () => {
  const answer =
    "**CLM-1012** needs you.\n\n| Claim | Payout |\n| --- | --- |\n| CLM-1012 | $1,150.00 |";
  await opened(conversation(turn({ answer })));
  expect(
    (await screen.findByText("What needs me?", { selector: "p" })).className,
  ).toBe("copilot-message");
  const table = await screen.findByRole("table");
  expect(within(table).getByRole("cell", { name: "$1,150.00" })).toBeDefined();
  const links = screen.getAllByRole("link", { name: "CLM-1012" });
  expect(links[0]?.getAttribute("href")).toBe("#/claims/CLM-1012");
  expect(screen.getByText("3 model calls · $0.0123 · 12s")).toBeDefined();
});

it("shows each card's tool, input and state, and opens to its detail", async () => {
  await opened(
    conversation(
      turn({
        steps: [
          step(),
          step({
            key: "call-2",
            kind: "context",
            tool: "lookup_term",
            input: "named storm",
            answer: '{"term": "named storm"}',
            sources: [
              {
                file: "glossary.yaml",
                system: "Policy admin",
                owner: "Data governance",
                reviewed: "2026-10-01",
              },
            ],
          }),
          step({
            key: "call-3",
            kind: "action",
            tool: "start_dispatch",
            input: "3",
            state: "refused",
            reason: "Refused (409): Dispatch 1 is running",
          }),
        ],
      }),
    ),
  );
  const steps = await screen.findByRole("list", { name: "Steps" });
  const names = within(steps)
    .getAllByRole("listitem")
    .map((card) => card.className);
  expect(names).toEqual([
    "copilot-card kind-claims state-done",
    "copilot-card kind-context state-done",
    "copilot-card kind-action state-refused",
  ]);
  expect(screen.getByText("Refused")).toBeDefined();
  expect(
    screen.getByText("Refused (409): Dispatch 1 is running"),
  ).toBeDefined();
  const lookup = screen.getByRole("button", {
    name: /lookup_term named storm/,
  });
  fireEvent.click(lookup);
  expect(lookup.getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("glossary.yaml")).toBeDefined();
  expect(screen.getByText(/owned by Data governance/)).toBeDefined();
});

it("shows a working card with a spinner and the seconds so far", async () => {
  const started = new Date(Date.now() - 4000).toISOString();
  await opened(
    conversation(
      turn({
        status: "working",
        answer: null,
        steps: [step({ state: "working", started_at: started })],
      }),
    ),
  );
  expect(await screen.findByText(/^Working \d+s$/)).toBeDefined();
  const box = screen.getByRole("textbox", { name: "Ask the Copilot" });
  expect((box as HTMLTextAreaElement).disabled).toBe(true);
});

it("asks for the confirmation first, and sends Sign off and pay or Cancel", async () => {
  const card = {
    claim_id: "CLM-1003",
    customer: "Aiko Tanaka",
    amount: 3750,
    reason: "The wording covers it.",
    policy_section: "3. Trip Delay",
  };
  const waiting = conversation(
    turn({ status: "waiting", answer: null, confirmation: card }),
  );
  const fetchMock = await opened(waiting);
  const confirmCard = await screen.findByRole("region", {
    name: "Confirm the sign-off",
  });
  expect(within(confirmCard).getByText("$3,750.00")).toBeDefined();
  expect(within(confirmCard).getByText("Aiko Tanaka")).toBeDefined();
  const box = screen.getByRole("textbox", { name: "Ask the Copilot" });
  expect(box.getAttribute("placeholder")).toBe("Answer the confirmation first");
  fireEvent.click(screen.getByRole("button", { name: "Sign off and pay" }));
  await waitFor(() => {
    const answered = fetchMock.mock.calls.filter(([input]) =>
      pathOf(input).endsWith("/confirmation"),
    );
    expect(answered[0]?.[1]?.body).toBe(JSON.stringify({ confirmed: true }));
  });
  fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  await waitFor(() => {
    const answered = fetchMock.mock.calls.filter(([input]) =>
      pathOf(input).endsWith("/confirmation"),
    );
    expect(answered[1]?.[1]?.body).toBe(JSON.stringify({ confirmed: false }));
  });
});

it("says what went wrong in a failed turn and a stopped one", async () => {
  await opened(
    conversation(
      turn({ status: "failed", answer: null, error: "The model is down" }),
      turn({ turn_id: 2, status: "stopped", answer: null }),
    ),
  );
  const alerts = await screen.findAllByRole("alert");
  expect(alerts.map((alert) => alert.textContent)).toEqual([
    "Something went wrong: The model is down. You can carry on with a new message.",
    "The Copilot stopped before it finished. You can carry on with a new message.",
  ]);
});

it("lists the earlier conversations newest first, as the app gives them", async () => {
  stubBackend({ "/api/conversations": LIST });
  render(<Copilot handler={dana} onCollapse={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Earlier" }));
  const list = await screen.findByRole("list", {
    name: "Earlier conversations",
  });
  expect(
    within(list)
      .getAllByRole("button")
      .map((b) => b.textContent),
  ).toEqual(["What needs me?", "Why does CLM-1003 need me?"]);
});

it("sends with Enter and starts a new line with Shift and Enter", async () => {
  const fetchMock = stubBackend({
    "/api/conversations": [],
    "POST /api/conversations": conversation(turn()),
  });
  render(<Copilot handler={marcus} onCollapse={vi.fn()} />);
  const box = screen.getByRole("textbox", { name: "Ask the Copilot" });
  fireEvent.change(box, { target: { value: "Sign off CLM-1003" } });
  fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(true);
  });
});

it("passes on the app's refusal of a message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve(
        init?.method === "POST"
          ? new Response(
              JSON.stringify({ detail: "Answer the confirmation first" }),
              { status: 409 },
            )
          : new Response(JSON.stringify([])),
      ),
    ),
  );
  render(<Copilot handler={dana} onCollapse={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "What needs me today?" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Answer the confirmation first",
  );
});

it("collapses to a tab the browser remembers, and opens again", async () => {
  stubBackend({
    "/api/claims": [summary()],
    "/api/handlers": [dana],
    "/api/conversations": [],
  });
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Collapse the Copilot" }),
  );
  expect(localStorage.getItem("undercover-copilot")).toBe("closed");
  expect(screen.queryByRole("complementary", { name: "Copilot" })).toBeNull();
  cleanup();
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Open the Copilot" }),
  );
  expect(screen.getByRole("complementary", { name: "Copilot" })).toBeDefined();
  expect(localStorage.getItem("undercover-copilot")).toBe("open");
});

it("links each claim id once, leaving links alone", () => {
  expect(linkClaims("See CLM-1012 and [CLM-1003](#/claims/CLM-1003).")).toBe(
    "See [CLM-1012](#/claims/CLM-1012) and [CLM-1003](#/claims/CLM-1003).",
  );
});

it("gives one model call in the singular", () => {
  expect(
    turnLine(turn({ model_calls: 1, cost: 0, ended_at: turn().started_at })),
  ).toBe("1 model call · $0.00 · 0s");
});

it("keeps the box disabled from the moment a message is sent", async () => {
  const working = conversation(
    turn({ status: "working", answer: null, steps: [] }),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify(working)));
      }
      if (pathOf(input) === "/api/conversations") {
        return Promise.resolve(new Response(JSON.stringify([])));
      }
      return new Promise<Response>(() => undefined); // the first read is slow
    }),
  );
  render(<Copilot handler={dana} onCollapse={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "What needs me today?" }));
  expect(await screen.findByRole("status")).toBeDefined();
  const box = screen.getByRole("textbox", { name: "Ask the Copilot" });
  expect((box as HTMLTextAreaElement).disabled).toBe(true);
});
