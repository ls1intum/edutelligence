import { formatRateUsd, formatUsd, formatUsdDollars, usdPerDisplayUnit } from './currency';

describe('formatUsd', () => {
  it('converts micro-cents to dollars (one unit = 1e8 micro-cents)', () => {
    expect(formatUsd(100_000_000)).toBe('$1.00');
    expect(formatUsd(0)).toBe('$0.00');
  });

  it('widens precision for small amounts', () => {
    expect(formatUsd(1_000)).toBe('$0.000010');
  });
});

describe('formatUsdDollars', () => {
  it('keeps the same precision tiers as formatUsd', () => {
    expect(formatUsdDollars(1)).toBe('$1.00');
    expect(formatUsdDollars(0.00001)).toBe('$0.000010');
    expect(formatUsdDollars(0)).toBe('$0.00');
  });
});

describe('formatRateUsd', () => {
  it('keeps three decimals for sub-dollar rates below $0.10', () => {
    expect(formatRateUsd(0.016)).toBe('$0.016');
    expect(formatRateUsd(0.028)).toBe('$0.028');
    expect(formatRateUsd(0.075)).toBe('$0.075');
  });

  it('keeps supported tiny per-second rates legible instead of "$0.0000"', () => {
    // PriceUpdaterService accepts and tests $0.000006 per second.
    expect(formatRateUsd(0.000006)).toBe('$0.000006');
    expect(formatRateUsd(0.000016)).toBe('$0.000016');
    expect(formatRateUsd(0.00000006)).toBe('$0.00000006');
  });

  it('keeps at least two decimals for round rates', () => {
    expect(formatRateUsd(0.01)).toBe('$0.01');
    expect(formatRateUsd(0.1)).toBe('$0.10');
    expect(formatRateUsd(2.5)).toBe('$2.50');
    expect(formatRateUsd(0)).toBe('$0.00');
  });
});

describe('usdPerDisplayUnit', () => {
  it('converts micro-cents per 1k tokens to dollars per 1M tokens', () => {
    // gpt-4o: 2.5e-6 USD/token -> 250000 micro-cents/1k tokens.
    expect(usdPerDisplayUnit(250_000, 'token')).toBeCloseTo(2.5, 10);
    expect(usdPerDisplayUnit(250_000, 'character')).toBeCloseTo(2.5, 10);
    expect(usdPerDisplayUnit(250_000, 'pixel')).toBeCloseTo(2.5, 10);
  });

  it('treats the per-1k-ms rate as the per-second rate', () => {
    // $0.016/s stored as 1.6e6 micro-cents/1k ms.
    expect(usdPerDisplayUnit(1_600_000, 'millisecond')).toBeCloseTo(0.016, 10);
  });

  it('divides discrete items by their per-1k scale', () => {
    // $0.01 per request stored as 1e9 micro-cents/1k requests.
    expect(usdPerDisplayUnit(1_000_000_000, 'request')).toBeCloseTo(0.01, 10);
    expect(usdPerDisplayUnit(1_000_000_000, 'image')).toBeCloseTo(0.01, 10);
  });
});
