/**
 * Costs are stored as micro-cents (`cost_micro_cents`) throughout the schema:
 * one currency unit = 100 cents = 1e8 micro-cents. Keep every conversion going
 * through this constant — dividing by 1e6 ("micro" applied to the unit rather
 * than to the cent) overstates every amount by a factor of 100.
 */
export const MICRO_CENTS_PER_UNIT = 100_000_000;

/**
 * Format micro-cents as a EUR amount, widening the precision for the small
 * per-request sums so they don't all collapse to "€0.00".
 */
export function formatEur(microCents: number): string {
  const euros = microCents / MICRO_CENTS_PER_UNIT;
  if (euros === 0) return '€0.00';
  if (euros < 0.0001) return `€${euros.toFixed(6)}`;
  if (euros < 0.01) return `€${euros.toFixed(4)}`;
  return `€${euros.toFixed(2)}`;
}
