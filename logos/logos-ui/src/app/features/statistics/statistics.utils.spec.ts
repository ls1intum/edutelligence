import { calculateDateRange, applyTimeSeriesLabels, chooseDynamicBucketMs, chooseDynamicTargetBuckets, toGb, parseVramSnapshot, donutArc, mergeWithLive } from './statistics.utils';
import type { RequestItem, PaginatedRequestItem } from './statistics.models';

describe('statistics.utils', () => {
  it('toGb converts bytes to binary GiB with 2 decimals', () => {
    expect(toGb(1024 * 1024 * 1024)).toBe(1);
    expect(toGb(1.5 * 1024 * 1024 * 1024)).toBe(1.5);
  });

  it('chooseDynamicTargetBuckets steps by span', () => {
    const day = 24 * 3600 * 1000;
    expect(chooseDynamicTargetBuckets(31 * day)).toBe(90);
    expect(chooseDynamicTargetBuckets(8 * day)).toBe(96);
    expect(chooseDynamicTargetBuckets(2 * day)).toBe(108);
    expect(chooseDynamicTargetBuckets(3600 * 1000)).toBe(120);
  });

  it('chooseDynamicBucketMs snaps to a nice candidate', () => {
    const hour = 3600 * 1000;
    expect(chooseDynamicBucketMs(120 * hour)).toBe(hour); // 120h / 120 buckets = 1h
  });

  it('parseVramSnapshot prefers configured total over used+remaining', () => {
    const snap = parseVramSnapshot({ used_vram_mb: 1024, remaining_vram_mb: 1024, total_vram_mb: 4096 });
    expect(snap.totalGb).toBe(toGb(4096 * 1024 * 1024));
  });

  it('calculateDateRange 30d spans ~30 days', () => {
    const { startDate, endDate } = calculateDateRange('30d');
    const days = (endDate.getTime() - startDate.getTime()) / (24 * 3600 * 1000);
    expect(Math.round(days)).toBe(30);
  });

  it('applyTimeSeriesLabels labels at most ~5 buckets and dedupes', () => {
    const now = Date.now();
    const series = Array.from({ length: 10 }, (_, i) => ({
      timestamp: now + i * 60000, label: '', cloud: 0, local: 0, total: 0, avgRunSeconds: null, avgVram: null,
    }));
    const out = applyTimeSeriesLabels(series, new Date(now), new Date(now + 9 * 60000));
    expect(out.filter(p => p.label !== '').length).toBeLessThanOrEqual(5);
  });

  it('donutArc returns non-empty path starting with M for a 90° segment', () => {
    const d = donutArc(100, 100, 90, 50, 0, Math.PI / 2);
    expect(d.length).toBeGreaterThan(0);
    expect(d.trimStart().startsWith('M')).toBe(true);
  });

  describe('mergeWithLive', () => {
    const BASE_TS = '2024-01-01T10:00:00.000Z';
    const LATER_TS = '2024-01-01T10:05:00.000Z';
    const EARLIEST_TS = '2024-01-01T09:55:00.000Z';

    const makePageItem = (overrides: Partial<PaginatedRequestItem> = {}): PaginatedRequestItem => ({
      request_id: 'req-1',
      model_name: 'model-a',
      provider_name: 'local-provider',
      is_cloud: false,
      status: 'success',
      timestamp: BASE_TS,
      duration: 1.5,
      cold_start: false,
      enqueue_ts: BASE_TS,
      scheduled_ts: null,
      request_complete_ts: BASE_TS,
      queue_seconds: 0.1,
      total_seconds: 1.6,
      initial_priority: null,
      priority_when_scheduled: null,
      queue_depth_at_enqueue: null,
      error_message: null,
      ...overrides,
    });

    const makeLiveItem = (overrides: Partial<RequestItem> = {}): RequestItem => ({
      request_id: 'req-1',
      model_name: 'model-a',
      provider_name: 'local-provider',
      status: 'error',
      timestamp: LATER_TS,
      duration: null,
      cold_start: null,
      enqueue_ts: LATER_TS,
      scheduled_ts: null,
      request_complete_ts: null,
      queue_seconds: null,
      total_seconds: null,
      initial_priority: null,
      priority_when_scheduled: null,
      queue_depth_at_enqueue: null,
      error_message: 'something went wrong',
      ...overrides,
    });

    it('live row overrides page row status but preserves page is_cloud', () => {
      const pageItem = makePageItem({ is_cloud: true, status: 'success' });
      const liveItem = makeLiveItem({ status: 'error' });

      const result = mergeWithLive([liveItem], [pageItem], 5);

      expect(result.length).toBe(1);
      expect(result[0].status).toBe('error');        // from live
      expect(result[0].is_cloud).toBe(true);         // preserved from page
    });

    it('extra live row not in page is appended', () => {
      const pageItem = makePageItem({ request_id: 'req-page', enqueue_ts: BASE_TS, timestamp: BASE_TS });
      const liveExtra = makeLiveItem({ request_id: 'req-live', enqueue_ts: LATER_TS, timestamp: LATER_TS });

      const result = mergeWithLive([liveExtra], [pageItem], 5);

      const ids = result.map(r => r.request_id);
      expect(ids).toContain('req-page');
      expect(ids).toContain('req-live');
      expect(result.length).toBe(2);
    });

    it('result is sorted descending by enqueue_ts', () => {
      const older = makePageItem({ request_id: 'req-old', enqueue_ts: EARLIEST_TS, timestamp: EARLIEST_TS });
      const newer = makeLiveItem({ request_id: 'req-new', enqueue_ts: LATER_TS, timestamp: LATER_TS });

      const result = mergeWithLive([newer], [older], 5);

      expect(result[0].request_id).toBe('req-new');
      expect(result[1].request_id).toBe('req-old');
    });

    it('result is capped at perPage', () => {
      const pageItems: PaginatedRequestItem[] = Array.from({ length: 3 }, (_, i) =>
        makePageItem({
          request_id: `page-${i}`,
          enqueue_ts: `2024-01-01T10:0${i}:00.000Z`,
          timestamp: `2024-01-01T10:0${i}:00.000Z`,
        })
      );
      const liveItems: RequestItem[] = Array.from({ length: 3 }, (_, i) =>
        makeLiveItem({
          request_id: `live-${i}`,
          enqueue_ts: `2024-01-01T11:0${i}:00.000Z`,
          timestamp: `2024-01-01T11:0${i}:00.000Z`,
        })
      );

      const result = mergeWithLive(liveItems, pageItems, 4);

      expect(result.length).toBe(4);
    });
  });
});
