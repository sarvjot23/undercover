// A stand-in for the judge, OpenRouter's Decisions endpoint: it gives every
// explanation the same grade, a B (2.0), and records the states it was asked about.
import { createServer } from "node:http";

const asked: unknown[] = [];

const ANSWER = {
  answers: {
    grade: {
      type: "score",
      score: 2.0,
      probabilities: { "0": 0.05, "1": 0.15, "2": 0.6, "3": 0.2 },
    },
    same_grounds: { type: "noul", noul: 0.9 },
    same_section: { type: "noul", noul: 0.3 },
  },
  model: "typesafe/jev-1.13",
  usage: { input_tokens: 400, output_tokens: 3, cost: 0.0001 },
};

createServer((request, response) => {
  let body = "";
  request.on("data", (chunk: Buffer) => {
    body += chunk.toString();
  });
  request.on("end", () => {
    response.setHeader("Content-Type", "application/json");
    if (request.method === "POST" && request.url === "/api/alpha/decisions") {
      asked.push((JSON.parse(body) as { state: unknown }).state);
      response.end(JSON.stringify(ANSWER));
      return;
    }
    response.end(JSON.stringify(request.url === "/asked" ? asked : {}));
  });
}).listen(8005, "127.0.0.1");
