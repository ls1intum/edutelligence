import { extractProviderHostRamMb, formatTokenCount } from './statistics.utils';

/**
 * The scale token counts are displayed on.
 *
 * A count that outgrows a unit steps up to the next magnitude — the 2470.7M
 * the statistics page used to show is 2.4 B — the unit is always the highest
 * applicable one, and a space separates the value from the unit.
 */
describe('formatTokenCount', () => {
  it('reads "0" for input that is not a positive finite number', () => {
    expect(formatTokenCount(0)).toBe('0');
    expect(formatTokenCount(-5)).toBe('0');
    expect(formatTokenCount(Number.NaN)).toBe('0');
    expect(formatTokenCount(Number.POSITIVE_INFINITY)).toBe('0');
    expect(formatTokenCount(null)).toBe('0');
    expect(formatTokenCount(undefined)).toBe('0');
  });

  it('keeps counts below the scale plain', () => {
    expect(formatTokenCount(1)).toBe('1');
    expect(formatTokenCount(512)).toBe('512');
    expect(formatTokenCount(999)).toBe('999');
  });

  it('steps up to K at 1.000 and nowhere before', () => {
    expect(formatTokenCount(1_000)).toBe('1 K');
    expect(formatTokenCount(1_500)).toBe('1.5 K');
    expect(formatTokenCount(999_999)).toBe('999.9 K');
  });

  it('steps up at every boundary of the scale', () => {
    expect(formatTokenCount(1_000_000)).toBe('1 M');
    expect(formatTokenCount(1_000_000_000)).toBe('1 B');
    expect(formatTokenCount(1_000_000_000_000)).toBe('1 T');
  });

  it('always uses the highest applicable magnitude', () => {
    // 2470.7M exceeds the million range, so it reads in billions — with the
    // space before the unit and the dot as decimal separator.
    expect(formatTokenCount(2_470_700_000)).toBe('2.4 B');
    expect(formatTokenCount(1_234_567)).toBe('1.2 M');
    expect(formatTokenCount(2_500_000_000)).toBe('2.5 B');
  });

  it('truncates to one decimal and drops it when it is zero', () => {
    // 2.4707 B shows the digit the count has — 2.4 — not the rounded 2.5, and
    // an exact value carries no trailing ".0".
    expect(formatTokenCount(2_470_700_000)).toBe('2.4 B');
    expect(formatTokenCount(1_999_999_999)).toBe('1.9 B');
    expect(formatTokenCount(262_144)).toBe('262.1 K');
    expect(formatTokenCount(40_960)).toBe('40.9 K');
  });

  it('stays on T once the scale is exhausted', () => {
    expect(formatTokenCount(2_000_000_000_000)).toBe('2 T');
    expect(formatTokenCount(15_000_000_000_000)).toBe('15 T');
  });
});


/**
 * Host RAM of a provider's latest sample.
 *
 * The distinction that matters here is "reported" vs "not reported": the
 * numbers travel on the runtime's host_memory summary, which older workers
 * never sent and non-Linux hosts report all-zero. Both have to read as "no
 * data" on the page, never as a machine with 0 MB of RAM.
 */
describe('extractProviderHostRamMb', () => {
  it('reads the three figures from the provider signals', () => {
    const sample = {
      timestamp: '2026-03-16T18:00:00Z',
      scheduler_signals: {
        provider: {
          host_ram_total_mb: 516_096,
          host_ram_used_mb: 204_048,
          host_ram_available_mb: 312_048,
        },
      },
    };
    expect(extractProviderHostRamMb(sample)).toEqual({
      totalMb: 516_096,
      usedMb: 204_048,
      freeMb: 312_048,
      reported: true,
    });
  });

  it('treats a sample without host RAM as not reported, not as zero', () => {
    // An older worker: the field is simply absent.
    expect(extractProviderHostRamMb({ timestamp: 't', scheduler_signals: { provider: {} } })).toEqual({
      totalMb: 0,
      usedMb: 0,
      freeMb: 0,
      reported: false,
    });
    expect(extractProviderHostRamMb(null)).toEqual({
      totalMb: 0,
      usedMb: 0,
      freeMb: 0,
      reported: false,
    });
    expect(extractProviderHostRamMb(undefined)).toEqual({
      totalMb: 0,
      usedMb: 0,
      freeMb: 0,
      reported: false,
    });
  });

  it('treats the all-zero non-Linux summary as not reported', () => {
    const sample = {
      timestamp: 't',
      scheduler_signals: {
        provider: { host_ram_total_mb: 0, host_ram_used_mb: 0, host_ram_available_mb: 0 },
      },
    };
    expect(extractProviderHostRamMb(sample).reported).toBe(false);
  });

  it('keeps a legitimately used host that is down to 0 MB available', () => {
    // 0 free is a real reading on an exhausted host — the page wants to show
    // that, so "reported" keys off the total, not the free figure.
    const sample = {
      timestamp: 't',
      scheduler_signals: {
        provider: { host_ram_total_mb: 65_536, host_ram_used_mb: 65_536, host_ram_available_mb: 0 },
      },
    };
    expect(extractProviderHostRamMb(sample)).toEqual({
      totalMb: 65_536,
      usedMb: 65_536,
      freeMb: 0,
      reported: true,
    });
  });
});
