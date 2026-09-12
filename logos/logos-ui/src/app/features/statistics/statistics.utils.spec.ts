import {
  extractProviderHostRamMb,
  formatPercent,
  formatTokenCount,
  normalizeFeedStatus,
  resolveFeedTotal,
  REQUEST_STATUS_FILTERS,
} from './statistics.utils';

/**
 * The dropdown's raw value becomes the bucket the feed is narrowed by.
 *
 * The empty selection is "all states", and a value that is not one of the four
 * buckets is treated the same way: it widens back to the full feed rather than
 * matching nothing, which is what an operator expects when a picker they did
 * not fill in stops showing everything.
 */
describe('normalizeFeedStatus', () => {
  it('turns the empty selection into "no filter"', () => {
    expect(normalizeFeedStatus('')).toBeNull();
    expect(normalizeFeedStatus(null)).toBeNull();
  });

  it('passes each lifecycle bucket through unchanged', () => {
    for (const bucket of REQUEST_STATUS_FILTERS) {
      expect(normalizeFeedStatus(bucket)).toBe(bucket);
    }
  });

  it('widens an unknown value back to the full feed', () => {
    // A stale or tampered value must not quietly match zero rows.
    expect(normalizeFeedStatus('pending')).toBeNull();
    expect(normalizeFeedStatus('ERROR')).toBeNull();
    expect(normalizeFeedStatus('queued ')).toBeNull();
  });
});

/**
 * Which "of N" total the feed header shows.
 *
 * Unfiltered, the feed and the KPI card count the same set, so the feed borrows
 * the aggregate. Filtered, it must show the count of that bucket — the aggregate
 * is only as narrow as the team/user scope — using the live push's total and
 * showing nothing at all while that push is still in flight.
 */
describe('resolveFeedTotal', () => {
  it('shows the aggregate total when no state filter is on', () => {
    // Even if a push carried a stale total, an unfiltered feed ignores it.
    expect(resolveFeedTotal(null, 3, 4312)).toBe(4312);
    expect(resolveFeedTotal('', 3, 4312)).toBe(4312);
  });

  it('shows the bucket total the live push reports', () => {
    expect(resolveFeedTotal('error', 7, 4312)).toBe(7);
    expect(resolveFeedTotal('finished', 0, 4312)).toBe(0);
  });

  it('shows nothing while the filtered push is in flight', () => {
    // The filter is set but its first push has not landed yet. The aggregate
    // describes the whole scope, not the bucket, so the header would promise
    // a set the filter has hidden — an absent total ("—") is the honest
    // figure until the bucket's own count lands.
    expect(resolveFeedTotal('queued', null, 4312)).toBeNull();
  });
});

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

/**
 * The share of a part in a total, as the cold-start KPI card shows it.
 *
 * The point is the small end: a share that integer rounding collapses to
 * "0%" — 694 of 317.265 local starts — must read as the percentage it is,
 * while an everyday share like 34% stays plain and a genuinely zero share
 * still reads "0%".
 */
describe('formatPercent', () => {
  it('reads "0%" when the total is not a positive finite number', () => {
    expect(formatPercent(5, 0)).toBe('0%');
    expect(formatPercent(5, -100)).toBe('0%');
    expect(formatPercent(5, Number.NaN)).toBe('0%');
    expect(formatPercent(5, Number.POSITIVE_INFINITY)).toBe('0%');
    expect(formatPercent(5, null)).toBe('0%');
    expect(formatPercent(5, undefined)).toBe('0%');
  });

  it('reads "0%" when the share is zero or the part is not a number', () => {
    expect(formatPercent(0, 317_265)).toBe('0%');
    expect(formatPercent(null, 100)).toBe('0%');
    expect(formatPercent(undefined, 100)).toBe('0%');
    expect(formatPercent(Number.NaN, 100)).toBe('0%');
  });

  it('keeps everyday shares of 10% and up plain', () => {
    expect(formatPercent(34, 100)).toBe('34%');
    expect(formatPercent(1, 2)).toBe('50%');
    expect(formatPercent(10, 10)).toBe('100%');
  });

  it('keeps one decimal for single-digit shares, dropped when it is zero', () => {
    expect(formatPercent(35, 1000)).toBe('3.5%');
    expect(formatPercent(1, 32)).toBe('3.1%'); // 3.125 keeps its first decimal
    expect(formatPercent(3, 100)).toBe('3%');
  });

  it('shows two decimals below one percent', () => {
    // The case the helper exists for: 694 of 317.265 is 0.22%, not "0%".
    expect(formatPercent(694, 317_265)).toBe('0.22%');
    expect(formatPercent(1, 10_000)).toBe('0.01%');
  });

  it('widens the decimals until the share reads non-zero', () => {
    expect(formatPercent(1, 300_000)).toBe('0.0003%');
    expect(formatPercent(1, 10_000_000)).toBe('0.00001%');
  });

  it('bounds a share too small for six decimals instead of reading "0%"', () => {
    // Past the widening loop's cap toFixed(6) still rounds to zero. A single
    // cold start among billions of starts is vanishingly rare, not absent —
    // reporting it as "0%" would contradict the point of the helper.
    expect(formatPercent(1, 10_000_000_000)).toBe('<0.000001%');
    expect(formatPercent(1, 1_000_000_000)).toBe('<0.000001%');
    // The last share that still fits six decimals keeps its exact reading.
    expect(formatPercent(1, 100_000_000)).toBe('0.000001%');
  });
});
