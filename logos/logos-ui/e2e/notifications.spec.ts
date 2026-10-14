import { test, expect } from '@playwright/test';

/**
 * The notification bell's live socket, through Traefik.
 *
 * `/api/ws/notifications` must reach the application server's socket. A
 * router rule that misses it sends the upgrade to the orchestrator's `/api`
 * catch-all instead, which has no such socket: the handshake fails, the bell
 * keeps reconnecting, and nothing in the unit tests notices.
 */
test('the notification socket connects through the proxy and stays open', async ({ page }) => {
  const socket = page.waitForEvent('websocket', {
    predicate: (ws) => ws.url().includes('/api/ws/notifications'),
    timeout: 30_000,
  });
  await page.goto('/user-management');
  await expect(page.locator('app-notification-bell .bell')).toBeVisible();

  const ws = await socket;
  // A refused handshake closes the socket right away; an accepted one stays
  // open until the page leaves.
  await page.waitForTimeout(3_000);
  expect(ws.isClosed(), 'notification socket was closed: handshake refused or routed elsewhere').toBe(false);
});
