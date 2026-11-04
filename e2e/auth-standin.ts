// A stand-in for Supabase Auth: it signs our handlers in with ES256 tokens from a
// key of its own, publishes the public key, and answers the browser's CORS checks.
import type { IncomingMessage, ServerResponse } from "node:http";
import { createServer } from "node:http";
import { generateKeyPairSync, randomUUID, sign } from "node:crypto";
import { readFileSync } from "node:fs";

const PASSWORD = "e2e-password";
const KID = "e2e-key";
const { privateKey, publicKey } = generateKeyPairSync("ec", {
  namedCurve: "P-256",
});
const handlers = JSON.parse(
  readFileSync(new URL("../data/handlers.json", import.meta.url), "utf-8"),
) as { email: string }[];
const emails = new Set(handlers.map((handler) => handler.email));

function base64url(value: string | Buffer): string {
  return Buffer.from(value).toString("base64url");
}

function token(email: string): string {
  const header = base64url(
    JSON.stringify({ alg: "ES256", typ: "JWT", kid: KID }),
  );
  const payload = base64url(
    JSON.stringify({
      sub: email,
      email,
      aud: "authenticated",
      role: "authenticated",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  );
  const signature = sign("sha256", Buffer.from(`${header}.${payload}`), {
    key: privateKey,
    dsaEncoding: "ieee-p1363",
  });
  return `${header}.${payload}.${base64url(signature)}`;
}

function user(email: string) {
  return {
    id: randomUUID(),
    aud: "authenticated",
    role: "authenticated",
    email,
    app_metadata: { provider: "email" },
    user_metadata: {},
    created_at: "2026-11-04T00:00:00Z",
  };
}

function session(email: string) {
  return {
    access_token: token(email),
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: base64url(email),
    user: user(email),
  };
}

function answer(response: ServerResponse, status: number, body?: unknown) {
  response.statusCode = status;
  response.setHeader("Content-Type", "application/json");
  response.end(body === undefined ? "" : JSON.stringify(body));
}

type Reply = [number, unknown];
interface Sent {
  email?: string;
  password?: string;
  refresh_token?: string;
}

/** A password sign-in, or a refresh of an earlier one. */
function grant(url: URL, sent: Sent): Reply {
  if (url.searchParams.get("grant_type") === "refresh_token") {
    const email = Buffer.from(sent.refresh_token ?? "", "base64url").toString();
    return [200, session(email)];
  }
  const email = sent.email ?? "";
  if (emails.has(email) && sent.password === PASSWORD) {
    return [200, session(email)];
  }
  return [
    400,
    { code: "invalid_credentials", msg: "Invalid login credentials" },
  ];
}

/** The user a token was issued to. */
function tokenUser(request: IncomingMessage): Reply {
  const payload = request.headers.authorization?.split(".")[1] ?? "";
  const claims = JSON.parse(
    Buffer.from(payload, "base64url").toString() || "{}",
  ) as { email?: string };
  return claims.email ? [200, user(claims.email)] : [401, { msg: "No user" }];
}

const routes: Record<
  string,
  ((request: IncomingMessage, url: URL, sent: Sent) => Reply) | undefined
> = {
  "/auth/v1/.well-known/jwks.json": () => [
    200,
    {
      keys: [
        {
          ...publicKey.export({ format: "jwk" }),
          kid: KID,
          alg: "ES256",
          use: "sig",
        },
      ],
    },
  ],
  "/auth/v1/token": (_, url, sent) => grant(url, sent),
  "/auth/v1/user": (request) => tokenUser(request),
  "/auth/v1/logout": () => [204, undefined],
  "/health": () => [200, { status: "ok" }],
};

function respond(
  request: IncomingMessage,
  response: ServerResponse,
  body: string,
) {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  const route = routes[url.pathname];
  const sent = JSON.parse(body || "{}") as Sent;
  const [status, reply] = route
    ? route(request, url, sent)
    : [404, { msg: "Not found" }];
  answer(response, status, reply);
}

createServer((request, response) => {
  response.setHeader("Access-Control-Allow-Origin", "*");
  response.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  response.setHeader(
    "Access-Control-Allow-Headers",
    request.headers["access-control-request-headers"] ?? "*",
  );
  if (request.method === "OPTIONS") {
    answer(response, 204);
    return;
  }
  let body = "";
  request.on("data", (chunk: Buffer) => {
    body += chunk.toString();
  });
  request.on("end", () => {
    respond(request, response, body);
  });
}).listen(8004, "127.0.0.1");
