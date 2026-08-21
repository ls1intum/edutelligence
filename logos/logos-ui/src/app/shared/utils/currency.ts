/**
 * Costs are stored as micro-cents (`cost_micro_cents`) throughout the schema:
 * one currency unit = 100 cents = 1e8 micro-cents. Keep every conversion going
 * through this constant — dividing by 1e6 ("micro" applied to the unit rather
 * than to the cent) overstates every amount by a factor of 100.
 *
 * The unit is **USD**, not EUR. `token_prices` is filled by PriceUpdaterService
 * from litellm's model catalog, whose `input_cost_per_token` is USD per token
 * (gpt-4o reads 2.5e-6 = $2.50 per 1M tokens, its list price), scaled by 1e11 =
 * 1e8 micro-cents × 1e3 per-1k. No exchange rate is applied anywhere.
 */
export const MICRO_CENTS_PER_UNIT = 100_000_000;

/**
 * Format micro-cents as a USD amount, widening the precision for the small
 * per-request sums so they don't all collapse to "$0.00".
 */
export function formatUsd(microCents: number): string {
  const dollars = microCents / MICRO_CENTS_PER_UNIT;
  if (dollars === 0) return '$0.00';
  if (dollars < 0.0001) return `$${dollars.toFixed(6)}`;
  if (dollars < 0.01) return `$${dollars.toFixed(4)}`;
  return `$${dollars.toFixed(2)}`;
}
