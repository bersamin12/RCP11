import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // The pdf.js worker is an ES module. Vite's default build worker format is
  // "iife", which breaks it in the production bundle only -- and Playwright runs
  // the dev server, so the e2e suite cannot catch that. Verify with `npm run
  // build` served through FastAPI.
  worker: { format: "es" },
  build: { chunkSizeWarningLimit: 1400 },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
