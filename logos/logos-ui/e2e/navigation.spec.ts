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
      // empty, so the title alone is not enough — assert the *routed component*
      // rendered. Angular places it as the next sibling of its <router-outlet>.
      //
      // Scoped to the shell's outlet specifically: there are two in the tree —
      // app-root's, whose sibling is <app-shell> itself, and the shell's nested
      // one, whose sibling is the page. An unscoped `router-outlet + *` matches
      // both and fails strict mode. Matching `main` instead would be worse
      // still: shell.html wraps the outlet in <main class="main-content">, so
      // it is present on exactly the blank-page failure this test exists to
      // catch.
      await expect(page.locator('app-shell router-outlet + *')).toBeVisible();
      expect(failures, `unhandled exception on ${route.path}:\n${failures.join('\n')}`).toEqual([]);
    });
  }

  test('an unknown route lands somewhere real instead of a blank page', async ({ page }) => {
    await page.goto('/this-route-does-not-exist');

    // The wildcard redirects to /my-workspace, but that route is behind
    // hasKeysGuard, which fails closed and sends an admin to their home route
    // (/statistics for logos_admin) rather than to /no-access. The seeded admin
    // holds no API keys, so the landing page is the guard's decision, not the
    // wildcard's — asserting /my-workspace was asserting against the app's
    // actual behaviour.
    //
    // What matters for a 404 is that the user does not sit on a dead URL, so
    // that is what this checks: the bogus path is gone and the shell rendered
    // a real route.
    await expect(page).not.toHaveURL(/this-route-does-not-exist/);
    await expect(page.locator('app-shell router-outlet + *')).toBeVisible();
  });
});

test.describe('unauthenticated access', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('a protected route sends an anonymous visitor to the login page', async ({ page }) => {
    // Watching for the shell has to start before the navigation does. Asserting
    // only that the login button eventually appears would pass even if the
    // admin chrome painted first and was then replaced — and a flash of another
    // tenant's navigation is a real leak, not a cosmetic one.
    type ShellWatch = { __shellSeen: boolean; __shellWatchError?: string };

    await page.addInitScript(() => {
      const watch = window as unknown as ShellWatch;
      watch.__shellSeen = false;
      const check = () => {
        if (document.querySelector('app-shell, main.main-content')) {
          watch.__shellSeen = true;
        }
      };
      try {
        // Observe `document`, not `document.documentElement`. An init script can
        // run before the root element exists, and observing a null target
        // throws — after __shellSeen was already set to false. That exception
        // does not fail the test, so the assertion below would read false and
        // pass even if the shell did flash: a check that cannot fail.
        new MutationObserver(check).observe(document, { childList: true, subtree: true });
        check();
      } catch (error) {
        watch.__shellWatchError = String(error);
      }
    });

    await page.goto('/statistics');

    await expect(page.getByRole('button', { name: /sign in with tum/i })).toBeVisible({ timeout: 30_000 });

    const watch = await page.evaluate(() => {
      const w = window as unknown as ShellWatch;
      return { seen: w.__shellSeen, error: w.__shellWatchError };
    });

    // Assert the watcher attached before trusting what it reports, so a broken
    // observer surfaces as a failure rather than as a silent pass.
    expect(
      watch.error,
      `the shell observer never attached (${watch.error}), so this test could not have detected a flash`,
    ).toBeUndefined();
    expect(watch.seen, 'the authenticated shell rendered before the redirect to login').toBe(false);
  });
});
