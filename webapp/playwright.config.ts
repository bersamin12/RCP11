import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "/tmp/rcp-playwright-results",
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:4173",
    launchOptions: process.env.CI ? undefined : { executablePath: "/usr/bin/google-chrome" },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
  },
});
