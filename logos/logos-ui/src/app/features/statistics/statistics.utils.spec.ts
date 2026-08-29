import {
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
 * falling back to the aggregate only while that push is still in flight.
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

  it('falls back to the aggregate while the filtered push is in flight', () => {
    // The filter is set but its first push has not landed yet.
    expect(resolveFeedTotal('queued', null, 4312)).toBe(4312);
  });
});
