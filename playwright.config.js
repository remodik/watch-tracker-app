import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  timeout: 45000,
  use: { baseURL: "http://127.0.0.1:8773", trace: "retain-on-failure" },
  webServer: {
    command:
      (process.env.WATCH_TEST_PYTHON ?? ".venv/bin/python") +
      " -m tests.run_browser_server",
    url: "http://127.0.0.1:8773/api/health",
    timeout: 30000,
  },
});
