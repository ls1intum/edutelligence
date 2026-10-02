const MS_PER_DAY = 86_400_000;

/** Local calendar day as a UTC-midnight ordinal (DST-safe day difference). */
function localDayOrdinal(date: Date): number {
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / MS_PER_DAY;
}

/** Whole calendar days between the ISO timestamp and now (clamped to 0 for future). */
export function daysSince(iso: string, now: Date = new Date()): number {
  return Math.max(0, localDayOrdinal(now) - localDayOrdinal(new Date(iso)));
}

/** Local date as "DD.MM.YYYY", e.g. "02.06.1996". */
function formatGermanDate(d: Date): string {
  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  return `${day}.${month}.${d.getFullYear()}`;
}

/**
 * "DD.MM.YYYY" for the calendar date an ISO timestamp is valid on; "—" when
 * the value is missing/invalid.
 *
 * Catalogue `valid_from` values are UTC midnight: the first ten characters
 * are the effective date. Routing them through `new Date` would shift the
 * date by a day in UTC-negative time zones, so only the date part is read.
 */
export function formatIsoDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return '—';
  return `${match[3]}.${match[2]}.${match[1]}`;
}

/** Primary label and optional age line for a "last used" cell. */
export type LastUsedParts = { primary: string; age: string | null };

/**
 * Split "last used" into a primary line ("Never" / "Today" / "24.08.2026")
 * and an optional age line ("(2 days ago)") so table cells can stack them
 * instead of overflowing a single nowrap row.
 */
export function formatLastUsedParts(
  iso: string | null | undefined,
  now: Date = new Date(),
): LastUsedParts {
  if (!iso) return { primary: 'Never', age: null };
  const d = new Date(iso);
  const diffDays = localDayOrdinal(now) - localDayOrdinal(d);
  if (diffDays <= 0) return { primary: 'Today', age: null };
  const age = diffDays === 1 ? '(1 day ago)' : `(${diffDays} days ago)`;
  return { primary: formatGermanDate(d), age };
}

/**
 * "Last used" display for an ISO timestamp: "Never", "Today" or the German
 * date with the age in brackets, e.g. "24.08.2026 (2 days ago)".
 */
export function formatLastUsed(iso: string | null | undefined, now: Date = new Date()): string {
  const { primary, age } = formatLastUsedParts(iso, now);
  return age ? `${primary} ${age}` : primary;
}
