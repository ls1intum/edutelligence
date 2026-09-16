import { test, expect } from '@playwright/test';
import { SIMULATED_FLEET } from './fixtures';

/**
 * The UI's view of the worker fleet.
 *
 * This is the one place in the suite where simulated hardware travels the whole
 * length of the system: the GPU simulator answers `nvidia-smi`, the real worker
 * reports it over the WebSocket bridge, the orchestrator plans against it, and
 * the browser renders it. A panel that quietly falls back to a placeholder when
 * the shape of that payload changes is invisible to every other tier.
 */

test.describe('worker hardware', () => {
  test('the statistics page loads without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('pageerror', error => errors.push(error.message));

    await page.goto('/statistics');
    await expect(page).toHaveTitle(/Statistics/i);

    // The panels poll live worker state; give the first payload time to land.
    await page.waitForLoadState('networkidle');

    // Failed asset requests and auth noise are not what this asserts on —
    // an unhandled exception in a panel is.
    const real = errors.filter(text => !/favicon|net::ERR_|Failed to load resource/i.test(text));
    expect(real, `console errors on /statistics:\n${real.join('\n')}`).toEqual([]);
  });

  test('every simulated GPU reaches the browser', async ({ page }) => {
    await page.goto('/statistics');
    await page.waitForLoadState('networkidle');

    const body = page.locator('body');
    for (const node of SIMULATED_FLEET) {
      await expect(
        body,
        `the UI never showed ${node.gpu} — it is reported by a live simulated node`,
      ).toContainText(node.gpu, { timeout: 30_000 });
    }
  });

  test('the providers page lists the registered worker nodes', async ({ page }) => {
    await page.goto('/providers');
    await expect(page).toHaveTitle(/Providers/i);
    await page.waitForLoadState('networkidle');

    // Nodes self-register under their container hostname, so the assertion is on
    // the provider type rather than on a name that changes every run.
    await expect(page.locator('body')).toContainText(/logosnode/i, { timeout: 30_000 });
  });
});
