// A stand-in for the agent's service: it records what it's asked and does nothing.
import { createServer } from "node:http";

const received: { path: string | undefined; body: unknown }[] = [];

createServer((request, response) => {
  let body = "";
  request.on("data", (chunk: Buffer) => {
    body += chunk.toString();
  });
  request.on("end", () => {
    response.setHeader("Content-Type", "application/json");
    if (request.method === "POST") {
      received.push({
        path: request.url,
        body: body ? JSON.parse(body) : null,
      });
    }
    response.end(JSON.stringify(request.url === "/received" ? received : {}));
  });
}).listen(8003, "127.0.0.1");
