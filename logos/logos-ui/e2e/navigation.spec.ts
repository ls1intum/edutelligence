import { test, expect } from '@playwright/test';

/**
 * Route guards and lazy-loaded shells.
 *
 * Every route in `app.routes.ts` is a `loadComponent`, so a broken import or a
 * guard that throws surfaces as a blank page rather than a build failure — the
 * unit tests and the static export both stay green. Walking the routes in a
 * real browser is the only thing that catches it.
 */

const ADMIN_ROUTES = [
  { path: '/statistics', title: /Statistics/i },
  { path: '/models', title: /Models/i },
  { path: '/providers', title: /Providers/i },
  { path: '/policies', title: /Policies/i },
  { path: '/billing', title: /Billing/i },
  { path: '/user-management', title: /Users/i },
  { path: '/team-management', title: /Teams/i },
  { path: '/agents', title: /Agent Sessions/i },
];

test.describe('navigation as a Logos admin', () => {
  for (const route of ADMIN_ROUTES) {
    test(`${route.path} renders`, async ({ page }) => {
      const failures: string[] = [];
      page.on('pageerror', error => failures.push(error.message));

      await page.goto(route.path);

      await expect(page).toHaveTitle(route.title);
      // A lazy chunk that fails to load leaves the shell up and the outlet
      // empty, so the title alone is not enough — assert something rendered.
      await expect(page.locator('router-outlet + *, main, [role="main"]').first()).toBeVisible();
      expect(failures, `unhandled exception on ${route.path}:\n${failures.join('\n')}`).toEqual([]);
    });
  }

  test('an unknown route falls back to the workspace instead of a blank page', async ({ page }) => {
    await page.goto('/this-route-does-not-exist');
    await expect(page).toHaveURL(/my-workspace/);
  });
});

test.describe('unauthenticated access', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('a protected route sends an anonymous visitor to the login page', async ({ page }) => {
    await page.goto('/statistics');

    // The guard must not let the shell paint first — a flash of admin chrome
    // before the redirect is a real leak, not a cosmetic one.
    await expect(page.getByRole('button', { name: /sign in with tum/i })).toBeVisible({ timeout: 30_000 });
  });
});
