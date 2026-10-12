import { test, expect } from '@playwright/test';

/**
 * The public statistics page: the one Logos route that answers without a
 * session, and the team opt-in that decides whose traffic it shows.
 *
 * The stack's seed carries no request logs and no opted-in team, so an
 * anonymous visit must land on the *empty state* — an error state there
 * would mean /api/stats did not reach the webservice at all (the router
 * missing from the compose file, the endpoint 404ing behind the UI
 * catch-all), which a login-gated spec could never catch.
 */

test.describe('the public statistics page', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('renders for a visitor without an account', async ({ page }) => {
    const failures: string[] = [];
    page.on('pageerror', error => failures.push(error.message));

    await page.goto('/stats');

    await expect(page).toHaveTitle(/Public Statistics/i);
    await expect(page.getByRole('heading', { name: /Logos Public Statistics/i })).toBeVisible();
    // The range selector and the loading-to-empty transition prove the page
    // actually fetched /api/stats through Traefik instead of erroring out.
    await expect(page.getByRole('button', { name: '30 days' })).toBeVisible();
    await expect(page.getByText('No shared usage in this period yet.')).toBeVisible({ timeout: 30_000 });
    // A redirect to the login page would still leave this heading on screen
    // for a moment, so check the sign-in button stayed away, not just the URL.
    await expect(page.getByRole('button', { name: /sign in with tum/i })).toHaveCount(0);

    expect(failures, `unhandled exception on /stats:\n${failures.join('\n')}`).toEqual([]);
  });
});

test.describe('the team opt-in', () => {
  test('survives a re-entry into the team settings', async ({ page }) => {
    await page.goto('/team-management');

    // The seeded 'e2e' team is the only one; re-entering it after the toggle
    // reloads the team from the application server, so a checkbox that only
    // changed in memory would show up unchecked again.
    const teamRow = page.locator('.table-row', { hasText: 'e2e' }).first();
    await teamRow.click();
    await page.getByRole('tab', { name: 'Settings' }).click();

    const share = page.locator('#s-public-stats');
    await expect(share).toBeVisible();
    await expect(share).toBeChecked({ checked: false });

    await share.check();
    await expect(page.getByText('Saved!').first()).toBeVisible({ timeout: 30_000 });

    await page.goto('/team-management');
    await teamRow.click();
    await page.getByRole('tab', { name: 'Settings' }).click();
    await expect(share).toBeChecked({ checked: true });

    // Switch it off again: the stack is shared between specs.
    await share.uncheck();
    await expect(page.getByText('Saved!').first()).toBeVisible({ timeout: 30_000 });
    await expect(share).toBeChecked({ checked: false });
  });
});
