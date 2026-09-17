import { test as setup, expect } from '@playwright/test';
import { ADMIN_USER, STORAGE_STATE } from './fixtures';

/**
 * Log in once through the real Keycloak and store the session.
 *
 * Driving the actual OIDC redirect rather than injecting a token is the point:
 * the redirect back into the SPA, the token exchange, and the role mapping the
 * route guards read are all part of what breaks, and none of it is exercised by
 * a hand-placed token.
 *
 * The Keycloak form is addressed by element id, not by accessible name. Its
 * login page renders a show/hide toggle whose accessible name also contains
 * "password", so `getByLabel(/password/i)` matches two elements and fails
 * Playwright's strict mode. `#username` / `#password` / `#kc-login` are
 * Keycloak's own long-standing ids and are unambiguous.
 */
setup('authenticate as a Logos admin', async ({ page }) => {
  await page.goto('/');

  // This is the first page load of the run, so it pays for the Angular bundle
  // and first paint; wait explicitly rather than let that read as a broken
  // login page.
  //
  // A generous timeout is not the reason this button was once missing for a
  // full 60s, though — that was the stack being declared ready before the
  // webservice could serve `/api/info`, which the app's initializer blocks on,
  // so Angular never bootstrapped and no button was ever going to appear. That
  // is fixed where it belongs, in `compose.ui_is_up()`.
  const signIn = page.getByRole('button', { name: /sign in with tum/i });
  await expect(signIn).toBeVisible({ timeout: 60_000 });
  await signIn.click();

  // Keycloak's own login form, on its own origin.
  await page.waitForURL(/\/realms\/tum\/protocol\/openid-connect\/auth/, { timeout: 30_000 });
  await page.locator('#username').fill(ADMIN_USER.username);
  await page.locator('#password').fill(ADMIN_USER.password);

  // `#kc-login` is the canonical id, but it has moved between an <input> and a
  // <button> across Keycloak themes; fall back to the form's submit control.
  // Scoping to the form keeps the show/hide-password toggle out of the match.
  const submit = page
    .locator('#kc-login')
    .or(page.locator('#kc-form-login button[type="submit"], #kc-form-login input[type="submit"]'));
  await submit.first().click();

  // Back in the SPA, past the auth guard. The landing route depends on the
  // account's roles, so this waits for the authenticated shell to mount rather
  // than for one specific path.
  await expect(page.locator('app-shell')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('button', { name: /sign in with tum/i })).toHaveCount(0);

  await page.context().storageState({ path: STORAGE_STATE });
});
