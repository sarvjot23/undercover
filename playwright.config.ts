import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// The end-to-end run has its own ports and a fresh database each time.
// Workers load this file again, so they take the path the main process chose.
const database =
  process.env.UNDERCOVER_E2E_DB ??
  join(tmpdir(), `undercover-e2e-${String(Date.now())}.db`);
// The tests play the agent's part, against a stand-in for its service on its own port.
process.env.UNDERCOVER_E2E_DB = database;

export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/test-results",
  reporter: "list",
  workers: 1,
  use: { baseURL: "http://localhost:5174" },
  webServer: [
    {
      command: "node e2e/agent-standin.ts",
      url: "http://127.0.0.1:8003/health",
    },
    {
      command: "uv run -m uvicorn backend.api:app --port 8001",
      url: "http://127.0.0.1:8001/api/health",
      env: {
        UNDERCOVER_DB: database,
        UNDERCOVER_AGENT: "http://127.0.0.1:8003",
        DATABASE_URL: "",
      },
    },
    {
      command: "npx vite dashboard --port 5174 --strictPort",
      url: "http://localhost:5174",
      env: { BACKEND_URL: "http://127.0.0.1:8001" },
    },
  ],
});
