import { TestBed } from '@angular/core/testing';

import { CloudLatencyPanel, formatDelayMs } from './cloud-latency-panel';
import { StatisticsService } from '../../statistics/services/statistics.service';
import type {
  CloudLatencyRow,
  CloudLatencyScope,
  CloudLatencyStats,
} from '../../statistics/services/cloud-latency.models';

const row = (over: Partial<CloudLatencyRow> = {}): CloudLatencyRow => ({
  modelId: 1,
  modelName: 'gpt-x',
  providerId: 2,
  providerName: 'azure',
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

const SCOPE: CloudLatencyScope = {
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

describe('CloudLatencyPanel', () => {
  let calls: Array<{ start: string; end: string; scope: CloudLatencyScope }>;
  let respond: (stats: CloudLatencyStats) => void;
  let reject: (err: unknown) => void;

  beforeEach(() => {
    calls = [];
    TestBed.configureTestingModule({
      imports: [CloudLatencyPanel],
      providers: [
        {
          provide: StatisticsService,
          useValue: {
            getCloudLatencyStats: (start: string, end: string, scope: CloudLatencyScope) => {
              calls.push({ start, end, scope });
              return new Promise<CloudLatencyStats>((res, rej) => {
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
    const fixture = TestBed.createComponent(CloudLatencyPanel);
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
    expect(rows[0].textContent).toContain('gpt-x');
    expect(rows[0].textContent).toContain('52.0 s');
    expect(rows[1].textContent).toContain('2 failed');
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
      'No finished cloud requests in the selected range.',
    );

    fixture.componentRef.setInput('end', '2026-10-19T13:00:00.000Z');
    fixture.detectChanges();
    reject(new Error('boom'));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Could not load cloud request delays.');
  });
});
