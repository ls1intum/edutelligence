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
  return formatUsdDollars(microCents / MICRO_CENTS_PER_UNIT);
}

/**
 * Format a dollar amount, widening the precision for small rates so they
 * don't all collapse to "$0.00" (mirrors {@link formatUsd}).
 */
export function formatUsdDollars(dollars: number): string {
  if (dollars === 0) return '$0.00';
  if (dollars < 0.0001) return `$${dollars.toFixed(6)}`;
  if (dollars < 0.01) return `$${dollars.toFixed(4)}`;
  return `$${dollars.toFixed(2)}`;
}

/**
 * Convert a catalogue rate (`price_per_k_unit`: micro-cents per 1000 units)
 * to the dollars AI providers quote list prices in: countable units
 * (token, character, pixel) per 1 million, durations per second, every
 * other unit (request, image, page, query, session, …) per single item.
 */
function trimTrailingZeros(text: string): string {
  return text.replace(/0+$/, '').replace(/\.$/, '');
}

/**
 * Format a catalogue list price. Unlike per-request totals (formatUsd),
 * rates below $1 keep up to three decimals: cache-read and batch rates such
 * as $0.028/1M would otherwise round to a cent and misquote the provider.
 * "$0.01" and "$0.10" keep at least two decimals.
 */
export function formatRateUsd(dollars: number): string {
  if (dollars === 0) return '$0.00';
  if (dollars < 0.01) return `$${dollars.toFixed(4)}`;
  if (dollars < 1) {
    const trimmed = trimTrailingZeros(dollars.toFixed(3));
    const [whole, frac = ''] = trimmed.split('.');
    if (frac === '') return `$${whole}.00`;
    return `$${whole}.${frac.padEnd(2, '0')}`;
  }
  return `$${dollars.toFixed(2)}`;
}

export function usdPerDisplayUnit(pricePerKUnitMicroCents: number, unit: string): number {
  if (unit === 'millisecond') {
    // 1000 ms is one second, so the per-1k-ms rate is the per-second rate.
    return pricePerKUnitMicroCents / MICRO_CENTS_PER_UNIT;
  }
  if (unit === 'token' || unit === 'character' || unit === 'pixel') {
    return pricePerKUnitMicroCents / (MICRO_CENTS_PER_UNIT / 1000);
  }
  return pricePerKUnitMicroCents / (MICRO_CENTS_PER_UNIT * 1000);
}
