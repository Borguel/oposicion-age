// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests-frontend",
  timeout: 30000,
  fullyParallel: true,
  webServer: {
    command: "python3 -m http.server 8123 --directory frontend",
    port: 8123,
    reuseExistingServer: !process.env.CI,
  },
  use: {
    baseURL: "http://localhost:8123",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
      : {},
  },
});
