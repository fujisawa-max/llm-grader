import { defineConfig, devices } from "@playwright/test";

// The application does not require video capture.  Keep it opt-in so a
// minimal CI image without Playwright's optional ffmpeg package can still run
// browser E2E; traces and failure screenshots remain enabled.
const captureVideo = process.env.PLAYWRIGHT_ENABLE_VIDEO === "1";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  reporter: [["list"], ["html", { outputFolder: "test-results/report", open: "never" }]],
  use: {
    baseURL: process.env.E2E_FRONTEND_URL || "http://127.0.0.1:13000",
    ...devices["Desktop Chrome"],
    viewport: { width: 1920, height: 1080 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: captureVideo ? "retain-on-failure" : "off",
  },
  projects: [{
    name: "chromium",
    use: {
      ...devices["Desktop Chrome"],
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
        ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } }
        : {}),
    },
  }],
  outputDir: "test-results/artifacts",
});
