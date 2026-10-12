import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';

import { PublicStats } from './public-stats';

const response = {
  range: { start: '2026-09-11T00:00:00Z', end: '2026-10-11T00:00:00Z' },
  totals: { requests: 1200, totalTokens: 3_400_000 },
  models: [
    { modelId: 1, modelName: 'gpt-4', requestCount: 900 },
    { modelId: 2, modelName: 'llama-3', requestCount: 300 },
  ],
  timeSeries: [
    { timestamp: 1770076800000, requests: 0 },
    { timestamp: 1770163200000, requests: 50 },
    { timestamp: 1770249600000, requests: 25 },
  ],
};

const DAY_MS = 86_400_000;

/** The start_date the page asks for: now minus the selected window. */
function startDateOf(request: TestRequest): number {
  const query = new URLSearchParams(request.request.url.split('?')[1] ?? '');
  return new Date(query.get('start_date') ?? '').getTime();
}

describe('PublicStats', () => {
  let component: PublicStats;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    component = TestBed.runInInjectionContext(() => new PublicStats());
    http = TestBed.inject(HttpTestingController);
  });

  async function settle(): Promise<void> {
    await vi.waitFor(() => expect(component.loading()).toBe(false));
  }

  it('fetches the default 30-day window on init and publishes the aggregates', async () => {
    component.ngOnInit();

    const request = http.expectOne(req => req.url.startsWith('/api/stats?start_date='));
    expect(Math.abs(Date.now() - startDateOf(request) - 30 * DAY_MS)).toBeLessThan(5000);
    request.flush(response);
    await settle();

    expect(component.data()).toEqual(response);
    expect(component.hasTraffic).toBe(true);
    expect(component.models).toHaveLength(2);
    expect(component.timeSeries).toHaveLength(3);
    http.verify();
  });

  it('shows the error state and keeps the page empty when the request fails', async () => {
    component.ngOnInit();

    const request = http.expectOne(req => req.url.startsWith('/api/stats?start_date='));
    request.flush('', { error: { status: 503, statusText: 'Service Unavailable' } });
    await settle();

    expect(component.data()).toBeNull();
    expect(component.loadError()).toContain('could not be loaded');
    http.verify();
  });

  it('refetches with the chosen window when the range changes', async () => {
    component.ngOnInit();
    http.expectOne(req => req.url.startsWith('/api/stats?start_date='))
      .flush(response);
    await settle();

    component.setRange(7);

    const second = http.expectOne(req => req.url.startsWith('/api/stats?start_date='));
    expect(Math.abs(Date.now() - startDateOf(second) - 7 * DAY_MS)).toBeLessThan(5000);
    second.flush(response);
    await settle();

    expect(component.rangeDays()).toBe(7);
    http.verify();
  });

  it('ignores the current range and any change while a load is in flight', async () => {
    component.ngOnInit();

    component.setRange(30);
    component.setRange(7);

    http.expectOne(req => req.url.startsWith('/api/stats?start_date='))
      .flush(response);
    await settle();

    // Neither call opened a second request: the first matched the active
    // range, the second arrived while the load was still running.
    expect(component.rangeDays()).toBe(30);
    http.verify();
  });

  it('scales the daily bars to the busiest day, with a floor for quiet days', async () => {
    component.ngOnInit();
    http.expectOne(req => req.url.startsWith('/api/stats?start_date='))
      .flush(response);
    await settle();

    expect(component.maxDailyRequests).toBe(50);
    expect(component.barHeight(50)).toBe(100);
    expect(component.barHeight(25)).toBe(50);
    // A nonzero day must stay visible, but an empty one must stay empty.
    expect(component.barHeight(1)).toBe(2);
    expect(component.barHeight(0)).toBe(0);
  });

  it('scales the model bars to the busiest model', async () => {
    component.ngOnInit();
    http.expectOne(req => req.url.startsWith('/api/stats?start_date='))
      .flush(response);
    await settle();

    expect(component.busiestModelCount).toBe(900);
    expect(component.modelShare(900)).toBe(100);
    expect(component.modelShare(300)).toBeCloseTo(33.33, 1);
    expect(component.modelShare(1)).toBe(2);
    expect(component.modelShare(0)).toBe(0);
  });

  it('shows an empty page with no scale when nothing was shared', async () => {
    component.ngOnInit();
    http.expectOne(req => req.url.startsWith('/api/stats?start_date='))
      .flush({
        range: { start: '2026-10-01T00:00:00Z', end: '2026-10-11T00:00:00Z' },
        totals: { requests: 0, totalTokens: 0 },
        models: [],
        timeSeries: [{ timestamp: 1770076800000, requests: 0 }],
      });
    await settle();

    expect(component.hasTraffic).toBe(false);
    expect(component.models).toEqual([]);
    // With no traffic there is no scale, so nothing may render as a bar.
    expect(component.maxDailyRequests).toBe(0);
    expect(component.barHeight(40)).toBe(0);
    expect(component.busiestModelCount).toBe(0);
    expect(component.modelShare(40)).toBe(0);
  });

  it('formats the counts and the displayed window', async () => {
    expect(component.formatCount(0)).toBe('0');
    expect(component.formatCount(null)).toBe('0');
    expect(component.formatCount(1234567)).toBe('1,234,567');

    component.ngOnInit();
    http.expectOne(req => req.url.startsWith('/api/stats?start_date='))
      .flush(response);
    await settle();

    // Month names plus day, joined by an en dash; the exact day depends on
    // the local time zone, so only the shape is asserted.
    expect(component.rangeLabel()).toMatch(/^[A-Z][a-z]{2} \d{1,2} – [A-Z][a-z]{2} \d{1,2}$/);
  });
});
