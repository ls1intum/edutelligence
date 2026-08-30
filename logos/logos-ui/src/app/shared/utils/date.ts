const MS_PER_DAY = 86_400_000;

/** Whole days between the ISO timestamp and now (clamped to 0 for future/rounding). */
export function daysSince(iso: string, now: Date = new Date()): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / MS_PER_DAY));
}

/** Local date as "DD.MM.YYYY", e.g. "02.06.1996". */
function formatGermanDate(d: Date): string {
  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  return `${day}.${month}.${d.getFullYear()}`;
}

/**
 * "Last used" display for an ISO timestamp: "Never", "Today" or the German
 * date with the age in brackets, e.g. "24.08.2026 (2 days ago)".
 */
export function formatLastUsed(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return 'Never';
  const d = new Date(iso);
  const diffDays = Math.floor((now.getTime() - d.getTime()) / MS_PER_DAY);
  if (diffDays <= 0) return 'Today';
  const age = diffDays === 1 ? '(1 day ago)' : `(${diffDays} days ago)`;
  return `${formatGermanDate(d)} ${age}`;
}
