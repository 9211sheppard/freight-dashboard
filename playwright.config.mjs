import { defineConfig } from '@playwright/test';

const port = 4173;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL,
    headless: true,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python scripts/playwright_server.py',
    url: `${baseURL}/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
  reporter: [['list']],
});
