import { defineConfig } from "@playwright/test";

// Drives the end-to-end stack (make e2e): the dashboard on 8013, the fake
// Telegram on 8081. The scenarios share one database and run in order.
export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts",
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 30_000 },
  reporter: "list",
  use: { baseURL: process.env.E2E_URL ?? "http://127.0.0.1:8013" },
});
