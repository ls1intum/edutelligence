import { test as setup, expect } from '@playwright/test';
import { ADMIN_USER, STORAGE_STATE } from './fixtures';

/**
 * Log in once through the real Keycloak and store the session.
 *
 * Driving the actual OIDC redirect rather than injecting a token is the point:
 * the redirect back into the SPA, the token exchange, and the role mapping the
 * route guards read are all part of what breaks, and none of it is exercised by
 * a hand-placed token.
 */
setup('authenticate as a Logos admin', async ({ page }) => {
  await page.goto('/');

  await page.getByRole('button', { name: /sign in with tum/i }).click();

  // Keycloak's own login form, on its own origin.
  await page.waitForURL(/\/realms\/tum\/protocol\/openid-connect\/auth/, { timeout: 30_000 });
  await page.getByLabel(/username|email/i).fill(ADMIN_USER.username);
  await page.getByLabel(/password/i).fill(ADMIN_USER.password);
  await page.getByRole('button', { name: /sign in|log in/i }).click();

  // Back in the SPA, past the auth guard. The landing route depends on the
  // account's roles, so this asserts on leaving the login page rather than on
  // arriving at one specific path.
  await page.waitForURL(url => !url.pathname.endsWith('/') || url.hash.length > 0, { timeout: 30_000 });
  await expect(page.locator('app-shell, [class*="shell"]').first()).toBeVisible({ timeout: 30_000 });

  await page.context().storageState({ path: STORAGE_STATE });
});
