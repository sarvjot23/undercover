// A stand-in for the agent's service: it records what it's asked and does nothing.
import { createServer } from "node:http";

const received: (string | undefined)[] = [];

createServer((request, response) => {
  response.setHeader("Content-Type", "application/json");
  if (request.method === "POST") received.push(request.url);
  response.end(JSON.stringify(request.url === "/received" ? received : {}));
}).listen(8003, "127.0.0.1");
