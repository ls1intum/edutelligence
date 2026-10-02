/**
 * Manual drag-and-drop ordering of a team's application keys.
 *
 * Only the SLA tier reaches the orchestrator (via `api_keys.default_priority`);
 * there is no server-side field for the order *within* a tier, so the manual
 * order is a per-browser display preference stored in `localStorage`. Keys the
 * stored order does not mention keep their server order, after the ones it does.
 */
const STORAGE_PREFIX = 'logos.app-keys.order.';

function storageKey(teamId: number): string {
  return `${STORAGE_PREFIX}${teamId}`;
}

export function loadKeyOrder(teamId: number): number[] {
  try {
    const raw = localStorage.getItem(storageKey(teamId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v): v is number => typeof v === 'number') : [];
  } catch {
    // Unreadable or disabled storage: fall back to the server order.
    return [];
  }
}

export function saveKeyOrder(teamId: number, keyIds: number[]): void {
  try {
    localStorage.setItem(storageKey(teamId), JSON.stringify(keyIds));
  } catch {
    // Storage full or disabled: the order simply does not survive a reload.
  }
}

/**
 * Rank of a key in the stored order. Unknown keys rank after every stored one,
 * keeping their relative server order via `fallbackIndex`.
 */
export function orderRank(order: number[], keyId: number, fallbackIndex: number): number {
  const i = order.indexOf(keyId);
  return i === -1 ? order.length + fallbackIndex : i;
}
