// A stand-in for the agent's AgentCore app: it answers /invocations and /ping and
// records each payload it's given. Like the agent off Runtime, it refuses a request
// without the agent's key. It plays a quick agent through the app's API, so the work
// the app starts ends and the next start isn't refused: it finishes each run, puts a
// proposal on each round it works, and finishes a round when it's carried on.
import { createServer } from "node:http";

const received: unknown[] = [];
const key = process.env.UNDERCOVER_API_KEY ?? "";
const app = process.env.UNDERCOVER_API ?? "";

/** The proposal the stand-in's improver makes on every round. */
export const PROPOSAL = {
  instructions: "Refer a claim when a required document is missing.",
  model: "openai/gpt-6-luna",
  reasoning: "medium",
  reason: "Three misses had a document missing.",
};

interface Payload {
  operation: string;
  run_id?: number;
  round_id?: number;
}

/** Play the agent's part in the work a payload starts, as the app's API allows. */
async function play(payload: Payload) {
  const post = (path: string, body?: object) =>
    fetch(`${app}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": key },
      body: body ? JSON.stringify(body) : undefined,
    });
  if (payload.operation === "work_run") {
    await post(`/api/runs/${String(payload.run_id)}/finish`);
  } else if (payload.operation === "work_round") {
    await post(
      `/api/rounds/${String(payload.round_id)}/proposals/change`,
      PROPOSAL,
    );
  } else if (payload.operation === "carry_round_on") {
    await post(`/api/rounds/${String(payload.round_id)}/finish`);
  }
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
    } else if (request.url === "/received") {
      response.end(JSON.stringify(received));
    } else if (request.headers.authorization !== `Bearer ${key}`) {
      response.statusCode = 401;
      response.end(
        JSON.stringify({ error: "The agent's key is missing or wrong" }),
      );
    } else {
      const payload = JSON.parse(body) as Payload;
      received.push(payload);
      response.end(JSON.stringify({ accepted: true }));
      setTimeout(() => void play(payload), 50);
    }
  });
}).listen(8003, "127.0.0.1");
