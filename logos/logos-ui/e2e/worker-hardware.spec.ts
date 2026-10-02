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

/**
 * Any card in the simulated fleet.
 *
 * Local Providers renders every connected worker at once, so any fleet GPU
 * model that reached the browser is enough to prove the hardware path works.
 * Exact fleet size is asserted separately via `.stats-glass-row` count.
 */
const ANY_FLEET_GPU = new RegExp(SIMULATED_FLEET.map(node => node.gpu).join('|'));

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
    // data is caught rather than raced past. Matches any fleet card, not a
    // named one — see ANY_FLEET_GPU.
    await expect(page.locator('body')).toContainText(ANY_FLEET_GPU, { timeout: 30_000 });

    // Failed asset requests and auth noise are not what this asserts on —
    // an unhandled exception in a panel is.
    const real = errors.filter(text => !/favicon|net::ERR_|Failed to load resource/i.test(text));
    expect(real, `console errors on /statistics:\n${real.join('\n')}`).toEqual([]);
  });

  test('the selected worker renders its real GPU model', async ({ page }) => {
    await page.goto('/statistics');
    await expect(page.locator(routedContent)).toBeVisible();

    // Local Providers shows every connected worker in its own glass row, so a
    // simulated GPU model from the fleet must reach the DOM rather than a
    // placeholder. Fleet completeness (exact node count) is asserted below.
    const body = page.locator('body');
    await expect(body, 'the panel reported no providers connected').not.toContainText(
      /No providers connected/i,
    );

    await expect(
      body,
      `no simulated GPU model reached the browser; expected one of ${SIMULATED_FLEET.map(n => n.gpu).join(', ')}`,
    ).toContainText(ANY_FLEET_GPU, { timeout: 30_000 });
  });

  test('both simulated workers appear on Local Providers', async ({ page }) => {
    await page.goto('/statistics');
    await expect(page.locator(routedContent)).toBeVisible();

    // Completeness check: every connected worker gets its own glass row, so a
    // node that registered but never reached the UI shows up as a missing row
    // rather than a silently narrower dropdown (the old provider <select>).
    const rows = page.locator('.stats-glass-row');
    await expect(
      rows,
      `expected one glass row per simulated worker (${SIMULATED_FLEET.length})`,
    ).toHaveCount(SIMULATED_FLEET.length, { timeout: 30_000 });

    // Each row header carries the provider name; container hostnames are random
    // hex per run, so assert the fleet size via rows rather than fixed labels.
    await expect(
      page.locator('body'),
      `no simulated GPU model reached the browser; expected one of ${SIMULATED_FLEET.map(n => n.gpu).join(', ')}`,
    ).toContainText(ANY_FLEET_GPU, { timeout: 30_000 });
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
