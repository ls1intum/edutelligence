import { defineConfig, devices } from '@playwright/test';

/**
 * Browser tier of the Logos E2E suite.
 *
 * Runs against the compose stack started with the `ui` profile
 * (`python -m harness.stack.compose up --ui` from `logos/e2e`). The base URL is
 * Traefik, not the UI container: in production the UI and the API share an
 * origin, and testing them on separate origins would miss every CORS, cookie
 * and same-origin-WebSocket problem that shape causes.
 *
 * The stack is not started here, for the same reason the pytest tiers do not
 * start it: a run that owns the lifecycle rebuilds images every time and tears
 * down the evidence at the moment a failure needs looking at.
 */
const UI_URL = process.env['E2E_UI_URL'] ?? `http://localhost:${process.env['E2E_UI_PORT'] ?? 18091}`;

export default defineConfig({
  testDir: '.',
  outputDir: './.playwright/results',
  // The UI reads live worker state; a flake here is usually a slow container,
  // not a slow assertion, so the per-assertion budget stays generous.
  expect: { timeout: 15_000 },
  timeout: 90_000,
  fullyParallel: false,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  // One worker: the specs share one seeded database and one worker fleet, so
  // parallel runs would be asserting on state each other is changing.
  workers: 1,
  reporter: process.env['CI']
    ? [['github'], ['html', { outputFolder: './.playwright/report', open: 'never' }]]
    : [['list']],
  use: {
    baseURL: UI_URL,
    // Kept on first retry only: traces are large, and the run that matters is
    // the one that failed twice.
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      // Logs in through the real Keycloak once and stores the session; every
      // other spec reuses it rather than re-driving the login form.
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: 'chromium',
      dependencies: ['setup'],
      use: {
        ...devices['Desktop Chrome'],
        storageState: './.playwright/admin-state.json',
      },
      testIgnore: /auth\.setup\.ts/,
    },
  ],
});
