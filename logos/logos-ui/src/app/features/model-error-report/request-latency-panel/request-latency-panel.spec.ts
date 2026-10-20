import { TestBed } from '@angular/core/testing';

import { RequestLatencyPanel, formatDelayMs } from './request-latency-panel';
import { StatisticsService } from '../../statistics/services/statistics.service';
import type {
  RequestLatencyRow,
  RequestLatencyScope,
  RequestLatencyStats,
} from '../../statistics/services/request-latency.models';

const row = (over: Partial<RequestLatencyRow> = {}): RequestLatencyRow => ({
  modelId: 1,
  modelName: 'gpt-x',
  providerId: 2,
  providerName: 'azure',
  local: false,
  reasoningEffort: null,
  requestCount: 10,
  errorCount: 0,
  queueP50Ms: 12,
  queueP95Ms: 52_000,
  upstreamP50Ms: 900,
  upstreamP95Ms: 2_400,
  ttftSamples: 10,
  ttftP50Ms: 400,
  ttftP95Ms: 53_000,
  ...over,
});

const SCOPE: RequestLatencyScope = {
  teamId: null,
  userId: null,
  providerId: null,
  apiKeyId: null,
  modelIds: [],
};

describe('formatDelayMs', () => {
  it('shows milliseconds below a second and seconds from a second on', () => {
    expect(formatDelayMs(12.4)).toBe('12 ms');
    expect(formatDelayMs(999)).toBe('999 ms');
    expect(formatDelayMs(1000)).toBe('1.0 s');
    expect(formatDelayMs(52_340)).toBe('52.3 s');
  });

  it('shows a dash when the figure is missing', () => {
    expect(formatDelayMs(null)).toBe('—');
    expect(formatDelayMs(undefined)).toBe('—');
    expect(formatDelayMs(Number.NaN)).toBe('—');
  });
});

describe('RequestLatencyPanel', () => {
  let calls: Array<{ start: string; end: string; scope: RequestLatencyScope }>;
  let respond: (stats: RequestLatencyStats) => void;
  let reject: (err: unknown) => void;

  beforeEach(() => {
    calls = [];
    TestBed.configureTestingModule({
      imports: [RequestLatencyPanel],
      providers: [
        {
          provide: StatisticsService,
          useValue: {
            getRequestLatencyStats: (start: string, end: string, scope: RequestLatencyScope) => {
              calls.push({ start, end, scope });
              return new Promise<RequestLatencyStats>((res, rej) => {
                respond = res;
                reject = rej;
              });
            },
          },
        },
      ],
    });
  });

  function create() {
    const fixture = TestBed.createComponent(RequestLatencyPanel);
    fixture.componentRef.setInput('start', '2026-10-19T00:00:00.000Z');
    fixture.componentRef.setInput('end', '2026-10-19T12:00:00.000Z');
    fixture.componentRef.setInput('scope', SCOPE);
    fixture.detectChanges();
    return fixture;
  }

  it('loads the range and scope it is given and renders one row per model and provider', async () => {
    const fixture = create();
    expect(calls).toEqual([
      { start: '2026-10-19T00:00:00.000Z', end: '2026-10-19T12:00:00.000Z', scope: SCOPE },
    ]);

    respond({
      range: { start: '', end: '' },
      rows: [row(), row({ providerName: 'openai', errorCount: 2 })],
    });
    await fixture.whenStable();
    fixture.detectChanges();

    const rows = fixture.nativeElement.querySelectorAll('.table-row');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('azure');
    expect(rows[0].textContent).toContain('52.0 s');
    expect(rows[1].textContent).toContain('2 failed');
  });

  it('shows the effort of each row, "default" when none was sent, and whether the provider is local', async () => {
    const fixture = create();
    respond({
      range: { start: '', end: '' },
      rows: [
        row({ providerName: 'node-a', local: true, reasoningEffort: 'xhigh' }),
        row({ providerName: 'node-a', local: true, reasoningEffort: null }),
        row({ providerName: 'azure', local: false, reasoningEffort: 'low' }),
      ],
    });
    await fixture.whenStable();
    fixture.detectChanges();

    const rows = fixture.nativeElement.querySelectorAll('.table-row');
    expect(rows.length).toBe(3);
    const effort = (r: Element) => r.querySelector('[data-label="Effort"]')?.textContent?.trim();
    const kind = (r: Element) => r.querySelector('.cell-kind')?.textContent?.trim();
    expect(effort(rows[0])).toBe('xhigh');
    expect(kind(rows[0])).toBe('Local');
    expect(effort(rows[1])).toBe('default');
    expect(rows[1].querySelector('.cell-muted')).not.toBeNull();
    expect(effort(rows[2])).toBe('low');
    expect(kind(rows[2])).toBe('Cloud');
  });

  it('shows how many requests the TTFT figures rest on', async () => {
    const fixture = create();
    respond({
      range: { start: '', end: '' },
      rows: [
        row({ requestCount: 60, ttftSamples: 5 }),
        row({ providerName: 'openai', requestCount: 10, ttftSamples: 10 }),
      ],
    });
    await fixture.whenStable();
    fixture.detectChanges();

    const rows = fixture.nativeElement.querySelectorAll('.table-row');
    const samples = (r: Element) =>
      r.querySelector('[data-label="TTFT samples"]')?.textContent?.replace(/\s+/g, ' ').trim();
    expect(samples(rows[0])).toBe('5 of 60');
    expect(samples(rows[1])).toBe('10');
  });

  it('reloads when the scope changes', async () => {
    const fixture = create();
    respond({ range: { start: '', end: '' }, rows: [] });
    await fixture.whenStable();

    fixture.componentRef.setInput('scope', { ...SCOPE, teamId: 7 });
    fixture.detectChanges();

    expect(calls.length).toBe(2);
    expect(calls[1].scope.teamId).toBe(7);
  });

  it('reloads the same range when the refresh counter changes', async () => {
    const fixture = create();
    respond({ range: { start: '', end: '' }, rows: [] });
    await fixture.whenStable();

    fixture.componentRef.setInput('refresh', 1);
    fixture.detectChanges();

    expect(calls.length).toBe(2);
    expect(calls[1]).toEqual(calls[0]);
  });

  it('says so when nothing is in range or the load fails', async () => {
    const fixture = create();
    respond({ range: { start: '', end: '' }, rows: [] });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(
      'No finished requests in the selected range.',
    );

    fixture.componentRef.setInput('end', '2026-10-19T13:00:00.000Z');
    fixture.detectChanges();
    reject(new Error('boom'));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Could not load request delays.');
  });
});
