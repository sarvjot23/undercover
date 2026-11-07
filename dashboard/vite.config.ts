import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // npm run dev and npm run build read the repo's .env when there is one, and the
  // environment otherwise; the unit and end-to-end tests set their own.
  envDir:
    mode === "development" || mode === "production"
      ? fileURLToPath(new URL("..", import.meta.url))
      : false,
  server: {
    proxy: { "/api": process.env.BACKEND_URL ?? "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    env: {
      VITE_SUPABASE_URL: "http://supabase.test",
      VITE_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test",
    },
    coverage: {
      include: ["src/**"],
      exclude: ["src/main.tsx"],
      thresholds: { statements: 80 },
    },
  },
}));
