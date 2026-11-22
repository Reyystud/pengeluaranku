import { defineConfig } from "@playwright/test";

/**
 * E2E runs against a running stack (PRD 8.3): E2E_BASE_URL, default the local Next.js server.
 * Registration is limited to 5 per hour per IP (FR-01) and refresh tokens rotate, so the flows run
 * serially in one browser page with one account (see flows.spec.ts).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
});
