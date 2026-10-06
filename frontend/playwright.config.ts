import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 8799);
// Use a preinstalled Chromium when provided (e.g. sandboxes); CI installs its own.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH;

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    // Real FastAPI app serving the built frontend; only the media engine is faked.
    command: "uv run --project ../backend python -m tests.e2e_server",
    cwd: "../backend",
    env: { DL_STATIC_DIR: `${process.cwd()}/dist`, E2E_PORT: String(port) },
    url: `http://127.0.0.1:${port}/api/v1/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
