// A stand-in for the Copilot's AgentCore app: it answers /invocations and /ping, and
// plays a scripted turn through the app with the handler's sign-in, as the Copilot
// does: a lookup, an action, a refusal, then a formatted answer. A message about
// signing off pauses on a confirmation card instead, and the handler's answer
// carries the turn on to its end. It asks for no key, like the Copilot on a laptop.
import { createServer } from "node:http";

const app = process.env.UNDERCOVER_API ?? "";
const STEP_MS = 400;

const CARD = {
  claim_id: "CLM-1003",
  customer: "Aiko Tanaka",
  amount: 3750,
  reason: "The trip was cut short by a named storm, which the wording covers.",
  policy_section: "4. Trip Interruption",
};

const ANSWER = [
  "**CLM-1003** needs your sign-off.",
  "",
  "| Claim | Payout |",
  "| --- | --- |",
  "| CLM-1003 | $3,750.00 |",
].join("\n");

interface Payload {
  operation: string;
  conversation_id?: string;
  turn_id?: number;
  message?: string;
  confirmed?: boolean;
  token?: string;
}

const pause = (ms: number) =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

function step(
  kind: string,
  tool: string,
  input: string,
  state: string,
  extra: { answer?: string; reason?: string; seconds?: number } = {},
) {
  return {
    kind,
    tool,
    input,
    state,
    seconds: extra.seconds ?? 0,
    asked: JSON.stringify({ input }),
    answer: extra.answer ?? "",
    reason: extra.reason ?? "",
    sources: [],
  };
}

/** Play the Copilot's part in a turn or an answer, through the app. */
async function play(payload: Payload) {
  const turn = `${app}/api/conversations/${payload.conversation_id ?? ""}/turns/${String(payload.turn_id)}`;
  const send = (method: string, path: string, body: object) =>
    fetch(`${turn}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${payload.token ?? ""}`,
      },
      body: JSON.stringify(body),
    });
  const card = (key: string, body: object) =>
    send("PUT", `/steps/${key}`, body);

  if (payload.operation === "answer") {
    await pause(STEP_MS);
    const said = payload.confirmed
      ? "Signed off CLM-1003 and paid $3,750.00"
      : "Nothing was signed off";
    await card(
      "sign-off",
      step("action", "sign_off", "CLM-1003", "done", {
        answer: said,
        seconds: 0.3,
      }),
    );
    await send("POST", "/finish", {
      answer: payload.confirmed
        ? "Done: CLM-1003 is paid $3,750.00."
        : "I haven't signed off CLM-1003. What would you like instead?",
      model_calls: 1,
      cost: 0.001,
    });
    return;
  }
  await card("lookup", step("claims", "get_claim", "CLM-1003", "working"));
  await pause(STEP_MS);
  await card(
    "lookup",
    step("claims", "get_claim", "CLM-1003", "done", {
      answer: '{"claim_id": "CLM-1003"}',
      seconds: 0.4,
    }),
  );
  if (/sign off/i.test(payload.message ?? "")) {
    await card(
      "sign",
      step("action", "sign_off_claim", "CLM-1003", "done", {
        answer: "Waiting for Dana Whitfield to confirm",
      }),
    );
    await send("POST", "/pause", { confirmation: CARD });
    return;
  }
  await pause(STEP_MS);
  await card(
    "dispatch",
    step("action", "start_dispatch", "3", "done", {
      answer: '{"run_id": 1}',
      seconds: 0.2,
    }),
  );
  await pause(STEP_MS);
  await card(
    "again",
    step("action", "start_dispatch", "3", "refused", {
      reason: "Refused (409): Dispatch 1 is running",
    }),
  );
  await pause(STEP_MS);
  await send("POST", "/finish", {
    answer: ANSWER,
    model_calls: 4,
    cost: 0.0042,
  });
}

createServer((request, response) => {
  let body = "";
  request.on("data", (chunk: Buffer) => {
    body += chunk.toString();
  });
  request.on("end", () => {
    response.setHeader("Content-Type", "application/json");
    if (request.url === "/ping") {
      response.end(JSON.stringify({ status: "Healthy" }));
      return;
    }
    const payload = JSON.parse(body) as Payload;
    if (payload.operation === "health") {
      response.end(JSON.stringify({ healthy: true }));
      return;
    }
    response.end(JSON.stringify({ accepted: true }));
    setTimeout(() => void play(payload), 50);
  });
}).listen(8007, "127.0.0.1");
