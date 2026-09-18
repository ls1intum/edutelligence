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
 * Never assert a *specific* model on the statistics page: the panel shows one
 * provider at a time and picks it by sorting on the worker name, which is the
 * container hostname — random hex per run. Naming one card passes or fails
 * depending on which node happened to sort first.
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

    // The panel shows one provider at a time: `activeProvider` resolves to a
    // single worker and `devices` returns only that worker's cards. An earlier
    // version of this test expected every simulated GPU on screen at once,
    // which the page never promised — it failed on the node that simply was not
    // the selected one. Fleet completeness is the API tier's job
    // (tests/node/test_node_registration.py asserts both nodes and their exact
    // hardware); what the browser has to prove is that the selected worker's
    // real model reaches the DOM rather than a placeholder.
    const body = page.locator('body');
    await expect(body, 'the panel reported no providers connected').not.toContainText(
      /No providers connected/i,
    );

    await expect(
      body,
      `no simulated GPU model reached the browser; expected one of ${SIMULATED_FLEET.map(n => n.gpu).join(', ')}`,
    ).toContainText(ANY_FLEET_GPU, { timeout: 30_000 });
  });

  test('both simulated workers are selectable', async ({ page }) => {
    await page.goto('/statistics');
    await expect(page.locator(routedContent)).toBeVisible();

    // The completeness check the test above cannot make: the provider selector
    // is where every connected worker becomes visible to an operator, so a node
    // that registered but never reached the UI shows up here as a missing
    // option rather than as a silently narrower dropdown.
    // app-select collapses to a plain label when it has one option or fewer, so
    // "not visible" here is itself the failure signal: it means fewer workers
    // reached the UI than registered, not that the control moved.
    const selector = page.getByLabel(/select provider/i);
    await expect(
      selector,
      'the provider <select> did not render — with one option or fewer app-select collapses, ' +
        'so this means fewer than two workers reached the statistics page',
    ).toBeVisible({ timeout: 30_000 });
    await expect(
      selector.locator('option'),
      `expected one option per simulated worker (${SIMULATED_FLEET.length})`,
    ).toHaveCount(SIMULATED_FLEET.length, { timeout: 30_000 });
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
