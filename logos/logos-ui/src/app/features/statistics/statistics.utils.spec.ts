import { formatTokenCount } from './statistics.utils';

/**
 * The scale token counts are displayed on (issue #816).
 *
 * A count that outgrows a unit steps up to the next magnitude — the 2470.7M
 * the issue was filed against is 2.470 B, not 2.470,7 M — the unit is always
 * the highest applicable one, and a space separates the value from the unit.
 */
describe('formatTokenCount', () => {
  it('keeps counts below the scale plain', () => {
    expect(formatTokenCount(0)).toBe('0');
    expect(formatTokenCount(1)).toBe('1');
    expect(formatTokenCount(512)).toBe('512');
    expect(formatTokenCount(999)).toBe('999');
  });

  it('steps up to K at 1.000 and nowhere before', () => {
    expect(formatTokenCount(1_000)).toBe('1.000 K');
    expect(formatTokenCount(1_500)).toBe('1.500 K');
    expect(formatTokenCount(999_999)).toBe('999.999 K');
  });

  it('steps up at every boundary of the scale', () => {
    expect(formatTokenCount(1_000_000)).toBe('1.000 M');
    expect(formatTokenCount(1_000_000_000)).toBe('1.000 B');
    expect(formatTokenCount(1_000_000_000_000)).toBe('1.000 T');
  });

  it('always uses the highest applicable magnitude', () => {
    // 2470.7M exceeds the million range, so it reads in billions — with the
    // space before the unit and the dot as decimal separator.
    expect(formatTokenCount(2_470_700_000)).toBe('2.470 B');
    expect(formatTokenCount(1_234_567)).toBe('1.234 M');
    expect(formatTokenCount(2_500_000_000)).toBe('2.500 B');
  });

  it('truncates the value rather than rounding it up', () => {
    // 2.4707 B shows the digits the count has — 2.470 — not the rounded 2.471.
    expect(formatTokenCount(2_470_700_000)).toBe('2.470 B');
    expect(formatTokenCount(1_999_999_999)).toBe('1.999 B');
  });

  it('stays on T once the scale is exhausted', () => {
    expect(formatTokenCount(2_000_000_000_000)).toBe('2.000 T');
    expect(formatTokenCount(15_000_000_000_000)).toBe('15.000 T');
  });
});
