import { defineConfig, devices } from '@playwright/test';

// Runs against an already-running stack (`make up`); no webServer is started here.
export default defineConfig({
  testDir: './e2e',
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
    // a missing page or control fails after 15 s instead of waiting for the whole test timeout
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  timeout: 60_000,
  expect: { timeout: 10_000 },
  projects: [
    {
      name: 'desktop-1440',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      // phone specs assert 360 px layout rules; they run only in the phone project
      testIgnore: '**/*.phone.spec.ts',
    },
    {
      name: 'phone-360',
      use: { ...devices['Pixel 5'], viewport: { width: 360, height: 740 } },
      testMatch: ['**/smoke.spec.ts', '**/*.phone.spec.ts'],
    },
  ],
});
