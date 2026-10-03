import { defineConfig, devices } from '@playwright/test';

// Runs against an already-running stack (`make up`); no webServer is started here.
export default defineConfig({
  testDir: './e2e',
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'desktop-1440',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    { name: 'phone-360', use: { ...devices['Pixel 5'], viewport: { width: 360, height: 740 } } },
  ],
});
