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
 *
 * None of these wait for `networkidle`. These pages poll live worker state and
 * hold a stats WebSocket open, so the network never goes idle and that wait can
 * only ever time out — it did, on all three tests here. Web-first assertions
 * retry on their own, which is both the correct tool and a faster one.
 */

/** The routed page has rendered inside the shell (not merely the shell itself). */
const routedContent = 'app-shell router-outlet + *';

test.describe('worker hardware', () => {
  test('the statistics page loads without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('pageerror', error => errors.push(error.message));

    await page.goto('/statistics');
    await expect(page).toHaveTitle(/Statistics/i);
    await expect(page.locator(routedContent)).toBeVisible();

    // Let the first poll land, so an error thrown while rendering live worker
    // data is caught rather than raced past.
    await expect(page.locator('body')).toContainText(SIMULATED_FLEET[0].gpu, { timeout: 30_000 });

    // Failed asset requests and auth noise are not what this asserts on —
    // an unhandled exception in a panel is.
    const real = errors.filter(text => !/favicon|net::ERR_|Failed to load resource/i.test(text));
    expect(real, `console errors on /statistics:\n${real.join('\n')}`).toEqual([]);
  });

  test('every simulated GPU reaches the browser', async ({ page }) => {
    await page.goto('/statistics');
    await expect(page.locator(routedContent)).toBeVisible();

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
    await expect(page.locator(routedContent)).toBeVisible();

    // Nodes self-register under their container hostname, so the assertion is on
    // the provider type rather than on a name that changes every run.
    await expect(page.locator('body')).toContainText(/logosnode/i, { timeout: 30_000 });
  });
});
