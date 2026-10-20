import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { provideRouter } from '@angular/router';

import { Statistics } from './statistics';
import { StatsWebsocketService } from './services/stats-websocket.service';
import { StatisticsService } from './services/statistics.service';

import type { FeedFilterOption, TimelineRequestConfig } from './statistics.models';

// The range the page shows is resolved from the calendar when it is picked,
// and then it sits: the server deliberately keeps the start where the preset
// put it and only slides the end to now. A page that stays open across
// midnight would otherwise keep counting the previous day's requests under a
// header that still says "Today" — the new day never starts at zero.
//
// The page's own ticker is what has to notice the period moved, and it has to
// apply the moved range exactly like a picked one. These tests run the ticker
// against a frozen clock and step it across a midnight the only way time can
// step it.
const wsSpy = () => ({
  connect: vi.fn(),
  disconnect: vi.fn(),
  reconnect: vi.fn(),
  setTimelineRange: vi.fn(),
  setScope: vi.fn(),
  setFeedStatus: vi.fn(),
  setFeedFilters: vi.fn(),
  setInterest: vi.fn(),
});

/** Boot the page at the frozen clock and wire in the service spies. */
async function pageAt(
  getScopeOptions: ReturnType<typeof vi.fn> = vi.fn().mockResolvedValue({
    teams: [],
    requesters: [],
    providers: [],
  }),
) {
  const ws = wsSpy();
  await TestBed.configureTestingModule({
    imports: [Statistics],
    providers: [
      { provide: StatsWebsocketService, useValue: ws },
      { provide: StatisticsService, useValue: { getScopeOptions } },
      // The page reads ?tab= and navigates on a tab switch, so it needs a real
      // router: without one construction fails before any test body runs.
      provideRouter([]),
    ],
  }).compileComponents();
  const fx = TestBed.createComponent(Statistics);
  // detectChanges runs ngOnInit through Angular's hook machinery so a later
  // signal-driven CD pass (e.g. the 30s ticker) does not re-fire it.
  fx.detectChanges();
  return { fx, component: fx.componentInstance, ws, getScopeOptions };
}

describe('Statistics calendar rollover', () => {
  let fixture: ComponentFixture<Statistics> | undefined;

  afterEach(() => {
    fixture?.destroy();
    fixture = undefined;
    vi.useRealTimers();
  });

  it('leaves the picked day alone while the calendar day holds', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 6, 23, 50, 0, 0));
    const page = await pageAt();
    fixture = page.fx;

    page.component.setPreset('day');
    // Flush the scope-options promise kicked off by the preset pick so the
    // quiet window below is not counting a late init resolution.
    await Promise.resolve();
    await Promise.resolve();
    const rangesBefore = page.ws.setTimelineRange.mock.calls.length;
    const connectsBefore = page.ws.connect.mock.calls.length;

    // 23:50 to 23:59, still the same day: every tick is a no-op.
    vi.advanceTimersByTime(9 * 60_000);

    expect(page.ws.setTimelineRange.mock.calls.length).toBe(rangesBefore);
    // The page is up and connected, so the silence is a decision, not an absence.
    expect(page.ws.connect).toHaveBeenCalledTimes(connectsBefore);
  });

  it('re-anchors the range at each midnight while the page stays open', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 6, 23, 50, 0, 0));
    const page = await pageAt();
    fixture = page.fx;

    page.component.setPreset('day');
    await Promise.resolve();
    await Promise.resolve();
    const rangesBefore = page.ws.setTimelineRange.mock.calls.length;
    const scopesBefore = page.getScopeOptions.mock.calls.length;

    // 23:50 to 00:10, with the midnight tick in between.
    vi.advanceTimersByTime(20 * 60_000);

    // The midnight tick — and only it: the following ticks compare against
    // the new period and stay quiet.
    expect(page.ws.setTimelineRange).toHaveBeenCalledTimes(rangesBefore + 1);

    // The resends name the new day, not a range that still reaches into the old one.
    const sent = page.ws.setTimelineRange.mock.calls[rangesBefore][0] as TimelineRequestConfig;
    const newMidnight = new Date(2026, 8, 7, 0, 0, 0, 0).toISOString();
    expect(sent.start).toBe(newMidnight);
    expect(sent.end).toBe(newMidnight);

    // The old numbers are marked stale until the server answers, so they are
    // never read as the new day's.
    expect(page.component.statsPending()).toBe(true);

    // The scope dropdowns are refilled for the range actually on screen.
    expect(page.getScopeOptions).toHaveBeenCalledTimes(scopesBefore + 1);
    expect(page.getScopeOptions.mock.calls.at(-1)?.[0]).toBe(newMidnight);

    // Left open a second night, the page re-anchors again rather than
    // accumulating three days under one heading.
    vi.advanceTimersByTime(23 * 3600_000 + 50 * 60_000);
    expect(page.ws.setTimelineRange).toHaveBeenCalledTimes(rangesBefore + 2);
    const second = page.ws.setTimelineRange.mock.calls[rangesBefore + 1][0] as
      TimelineRequestConfig;
    expect(second.start).toBe(new Date(2026, 8, 8, 0, 0, 0, 0).toISOString());
  });

  it('keeps the rolling 30-day window pinned across midnight', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 6, 23, 50, 0, 0));
    const page = await pageAt();
    fixture = page.fx;

    // The default preset: nothing to pick, just a clock to run.
    expect(page.component.preset()).toBe('30d');

    // 23:50 to 00:20 — the window's meaning ("last 30 days") never rolls, so
    // its start stays where the selection put it and nothing is re-sent.
    vi.advanceTimersByTime(30 * 60_000);

    expect(page.ws.setTimelineRange).not.toHaveBeenCalled();
  });

  it('leaves a user-picked custom range alone across midnight', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 6, 23, 50, 0, 0));
    const page = await pageAt();
    fixture = page.fx;

    page.component.setPreset('day');
    page.component.setCustomRange({
      start: new Date(2026, 8, 6, 12, 0),
      end: new Date(2026, 8, 6, 13, 0),
    });
    const rangesBefore = page.ws.setTimelineRange.mock.calls.length;

    vi.advanceTimersByTime(20 * 60_000);

    // A window the operator zoomed into is pinned where they put it; the
    // calendar moving underneath it is no reason to drag them out of it.
    expect(page.ws.setTimelineRange.mock.calls.length).toBe(rangesBefore);
  });
});

describe('Statistics scope options', () => {
  let fixture: ComponentFixture<Statistics> | undefined;

  afterEach(() => {
    fixture?.destroy();
    fixture = undefined;
    vi.useRealTimers();
  });

  it('discards a scope-options response a newer range and selection already superseded', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 6, 23, 50, 0, 0));

    // The init request is the one the operator outlives: it resolves only
    // after a range pick and a requester selection it does not know about.
    let releaseStale: (value: {
      teams: FeedFilterOption[];
      requesters: FeedFilterOption[];
      providers: FeedFilterOption[];
    }) => void = () => {};
    const stale = new Promise<{
      teams: FeedFilterOption[];
      requesters: FeedFilterOption[];
      providers: FeedFilterOption[];
    }>((resolve) => {
      releaseStale = resolve;
    });
    const fresh: {
      teams: FeedFilterOption[];
      requesters: FeedFilterOption[];
      providers: FeedFilterOption[];
    } = {
      teams: [{ id: 1, label: 'Team One', requestCount: 3 }],
      requesters: [{ id: 7, label: 'User Seven', requestCount: 5 }],
      providers: [],
    };
    // First request (the init one) is the one that outlives the operator;
    // everything after it serves the fresh range. State-based rather than
    // call-queued, so the test holds no matter how many init requests the
    // test harness fires.
    let first = true;
    const getScopeOptions = vi.fn(() => (first ? (first = false, stale) : Promise.resolve(fresh)));
    const page = await pageAt(getScopeOptions);
    fixture = page.fx;

    // The operator picks a range; the fresh response lands and the dropdowns
    // list it.
    page.component.setPreset('day');
    await Promise.resolve();
    await Promise.resolve();
    expect(page.component.feedUsers()).toEqual(fresh.requesters);
    expect(page.component.feedTeams()).toEqual(fresh.teams);

    // ...and narrows to a requester the stale response would not recognise.
    page.component.setUserFilter('u:7');
    await Promise.resolve();
    await Promise.resolve();
    const scopesBefore = page.ws.setScope.mock.calls.length;

    // The stale response lands last: empty lists, no user 7.
    releaseStale({ teams: [], requesters: [], providers: [] });
    await Promise.resolve();
    await Promise.resolve();

    // None of it may reach the page: the options of the current selection
    // stand, the chosen requester stays chosen, and no scope is re-sent for
    // lists that describe the previous range.
    expect(page.component.feedUsers()).toEqual(fresh.requesters);
    expect(page.component.feedTeams()).toEqual(fresh.teams);
    expect(page.component.filterUserId()).toBe(7);
    expect(page.ws.setScope.mock.calls.length).toBe(scopesBefore);
  });

  it('discards a stale response when the operator zooms into a custom range', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 6, 23, 50, 0, 0));

    // Same shape as the preset-pick race, one different move: the range
    // changes by zooming, and the in-flight request for the range the
    // operator zoomed away from must be superseded by it.
    let releaseStale: (value: {
      teams: FeedFilterOption[];
      requesters: FeedFilterOption[];
      providers: FeedFilterOption[];
    }) => void = () => {};
    const stale = new Promise<{
      teams: FeedFilterOption[];
      requesters: FeedFilterOption[];
      providers: FeedFilterOption[];
    }>((resolve) => {
      releaseStale = resolve;
    });
    const fresh: {
      teams: FeedFilterOption[];
      requesters: FeedFilterOption[];
      providers: FeedFilterOption[];
    } = {
      teams: [{ id: 1, label: 'Team One', requestCount: 3 }],
      requesters: [{ id: 7, label: 'User Seven', requestCount: 5 }],
      providers: [],
    };
    let first = true;
    const getScopeOptions = vi.fn(() => (first ? (first = false, stale) : Promise.resolve(fresh)));
    const page = await pageAt(getScopeOptions);
    fixture = page.fx;

    page.component.setCustomRange({
      start: new Date(2026, 8, 6, 12, 0),
      end: new Date(2026, 8, 6, 13, 0),
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(page.component.feedUsers()).toEqual(fresh.requesters);
    expect(page.component.feedTeams()).toEqual(fresh.teams);

    page.component.setUserFilter('u:7');
    await Promise.resolve();
    await Promise.resolve();
    const scopesBefore = page.ws.setScope.mock.calls.length;

    releaseStale({ teams: [], requesters: [], providers: [] });
    await Promise.resolve();
    await Promise.resolve();

    expect(page.component.feedUsers()).toEqual(fresh.requesters);
    expect(page.component.feedTeams()).toEqual(fresh.teams);
    expect(page.component.filterUserId()).toBe(7);
    expect(page.ws.setScope.mock.calls.length).toBe(scopesBefore);
  });
});

describe('recent request model and state filters', () => {
  let fixture: ComponentFixture<Statistics>;
  afterEach(() => {
    fixture?.destroy();
    vi.useRealTimers();
  });

  it('combines the model selection and status while keeping the page scope intact', async () => {
    const page = await pageAt();
    fixture = page.fx;
    page.component.statsPending.set(false);
    page.component.liveFeedTotal.set(12);
    page.component.setFeedModelFilter(['5001', '5002']);
    expect(page.component.requestFeedTotal()).toBeNull();
    // A model selection narrows the whole page: the cards and charts are
    // blanked until the server answers for it.
    expect(page.ws.setFeedFilters).toHaveBeenLastCalledWith(null, [5001, 5002], []);
    expect(page.component.statsPending()).toBe(true);
    page.component.statsPending.set(false);
    // The state bucket narrows the request list alone.
    page.component.setFeedStatusFilter('running');
    expect(page.ws.setFeedFilters).toHaveBeenLastCalledWith('running', [5001, 5002], []);
    expect(page.ws.setScope).not.toHaveBeenCalled();
    expect(page.component.statsPending()).toBe(false);
    expect(page.component.requestsPending()).toBe(true);
    const opts = page.ws.connect.mock.calls[0][0];
    opts.handlers.onRequestsData({ requests: [], total: 4 });
    expect(page.component.requestFeedTotal()).toBe(4);
    opts.handlers.onRequestsData({ requests: [] });
    expect(page.component.requestFeedTotal()).toBe(4);
    page.component.setPreset('day');
    expect(page.component.requestFeedTotal()).toBeNull();
    page.component.clearFilters();
    expect(page.ws.setFeedFilters).toHaveBeenLastCalledWith(null, [], []);
    expect(page.component.feedFilterActive()).toBe(false);
  });

  it('offers models from scope options', async () => {
    const page = await pageAt(vi.fn().mockResolvedValue({
      teams: [], requesters: [],
      models: [{ id: 5001, label: 'org/long-model', requestCount: 8 }],
      providers: [{ id: 6001, label: 'worker-with-a-long-name', requestCount: 8 }],
    }));
    fixture = page.fx;
    await Promise.resolve();
    expect(page.component.feedModelOptions()).toEqual([{ value: '5001', label: 'org/long-model (8)' }]);
  });

  it('prunes feed model selections that vanish from scope options', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 6, 23, 50, 0, 0));

    let resolveOptions: (value: {
      teams: FeedFilterOption[];
      requesters: FeedFilterOption[];
      providers: FeedFilterOption[];
      models: FeedFilterOption[];
    }) => void = () => {};
    const pending = new Promise<{
      teams: FeedFilterOption[];
      requesters: FeedFilterOption[];
      providers: FeedFilterOption[];
      models: FeedFilterOption[];
    }>((resolve) => {
      resolveOptions = resolve;
    });
    let first = true;
    const getScopeOptions = vi.fn(() =>
      first
        ? ((first = false),
          Promise.resolve({
            teams: [],
            requesters: [],
            models: [
              { id: 5001, label: 'keep', requestCount: 1 },
              { id: 5002, label: 'drop', requestCount: 1 },
            ],
            providers: [
              { id: 6001, label: 'keep-p', requestCount: 1 },
              { id: 6002, label: 'drop-p', requestCount: 1 },
            ],
          }))
        : pending,
    );
    const page = await pageAt(getScopeOptions);
    fixture = page.fx;
    await Promise.resolve();
    await Promise.resolve();

    page.component.setFeedModelFilter(['5001', '5002']);
    page.ws.setFeedFilters.mockClear();

    // Narrower range: only one model remains.
    page.component.setPreset('day');
    await Promise.resolve();
    resolveOptions({
      teams: [],
      requesters: [],
      models: [{ id: 5001, label: 'keep', requestCount: 1 }],
      providers: [{ id: 6001, label: 'keep-p', requestCount: 1 }],
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(page.component.feedModelIds()).toEqual(['5001']);
    expect(page.ws.setFeedFilters).toHaveBeenCalledWith(null, [5001], []);
  });
});

describe('requester picker: users and application keys', () => {
  let fixture: ComponentFixture<Statistics>;
  afterEach(() => {
    fixture?.destroy();
    vi.useRealTimers();
  });

  const options = () => ({
    teams: [],
    requesters: [{ id: 41, label: 'Ada Lovelace', requestCount: 30 }],
    providers: [],
    models: [],
    apiKeys: [
      { id: 41, label: 'Artemis · PROD', requestCount: 900 },
      { id: 42, label: 'Artemis · staging', requestCount: 12 },
    ],
  });

  it('offers people and application keys in one list, busiest first', async () => {
    const page = await pageAt(vi.fn().mockResolvedValue(options()));
    fixture = page.fx;
    await Promise.resolve();
    // A user and a key may share an id, so the value carries the kind.
    expect(page.component.userFilterOptions()).toEqual([
      { value: '', label: 'All requesters' },
      { value: 'k:41', label: 'App key: Artemis · PROD (900)' },
      { value: 'u:41', label: 'Ada Lovelace (30)' },
      { value: 'k:42', label: 'App key: Artemis · staging (12)' },
    ]);
  });

  it('narrows the page to either a user or a key, never both', async () => {
    const page = await pageAt(vi.fn().mockResolvedValue(options()));
    fixture = page.fx;
    await Promise.resolve();
    page.component.statsPending.set(false);

    page.component.setUserFilter('k:41');
    expect(page.ws.setScope).toHaveBeenLastCalledWith(
      expect.objectContaining({ userId: null, apiKeyId: 41 }),
    );
    // The cards and charts are blanked until the server answers for the key.
    expect(page.component.statsPending()).toBe(true);
    expect(page.component.selectedUserValue()).toBe('k:41');
    expect(page.component.filterLabel()).toBe('Artemis · PROD');
    expect(page.getScopeOptions).toHaveBeenLastCalledWith(
      expect.any(String), expect.any(String), expect.objectContaining({ apiKeyId: 41 }),
    );

    // Switching to a person drops the key.
    page.component.setUserFilter('u:41');
    expect(page.ws.setScope).toHaveBeenLastCalledWith(
      expect.objectContaining({ userId: 41, apiKeyId: null }),
    );
    expect(page.component.selectedUserValue()).toBe('u:41');

    page.component.setUserFilter('k:42');
    page.component.clearFilters();
    expect(page.ws.setScope).toHaveBeenLastCalledWith(
      expect.objectContaining({ userId: null, apiKeyId: null }),
    );
    expect(page.component.filterActive()).toBe(false);
  });

  it('drops a selected key the new range no longer holds', async () => {
    let calls = 0;
    const getScopeOptions = vi.fn(() =>
      Promise.resolve(calls++ === 0 ? options() : { ...options(), apiKeys: [] }),
    );
    const page = await pageAt(getScopeOptions);
    fixture = page.fx;
    await Promise.resolve();
    page.component.setUserFilter('k:42');
    await Promise.resolve();
    await Promise.resolve();

    expect(page.component.filterApiKeyId()).toBeNull();
    expect(page.ws.setScope).toHaveBeenLastCalledWith(expect.objectContaining({ apiKeyId: null }));
  });
});

describe('selector placement on the requests tab', () => {
  let fixture: ComponentFixture<Statistics>;
  afterEach(() => {
    fixture?.destroy();
    vi.useRealTimers();
  });

  it('keeps every selector in the page-top row and none in the recent-requests panel', async () => {
    const page = await pageAt();
    fixture = page.fx;
    // The filter row only renders on the requests tab; the route parameter is
    // what drives the tab in the browser, the signal is what drives the
    // template, so the test sets the signal directly.
    page.component.activeTab.set('requests');
    page.fx.detectChanges();
    const el = page.fx.nativeElement as HTMLElement;
    const scope = el.querySelector('.stats-scope') as HTMLElement;
    // The feed's model and state selectors sit in the page-top row with the
    // page scope ...
    expect(scope.querySelector('app-multi-select')).not.toBeNull();
    expect(scope.querySelector('select[aria-label="Filter requests by state"]')).not.toBeNull();
    // ... team / requester / provider are searchable single-selects (not a
    // second multi-select beside the feed), and outcomes are gone — only the
    // feed state selector remains for lifecycle buckets ...
    expect(scope.querySelectorAll('app-searchable-select')).toHaveLength(3);
    expect(scope.querySelector('[aria-label="Filter by outcome"]')).toBeNull();
    expect(
      el.querySelectorAll('[aria-label^="Filter by provider"]'),
    ).toHaveLength(1);
    // ... and the recent-requests panel carries no selectors of its own.
    const feedPanel = Array.from(el.querySelectorAll('app-stats-chart-panel')).find(
      (p) => p.textContent?.includes('Recent requests'),
    );
    expect(feedPanel).toBeDefined();
    expect(
      feedPanel?.querySelectorAll('app-select, app-multi-select, app-searchable-select'),
    ).toHaveLength(0);
  });
});

describe('local providers: failed GPUs and offline workers', () => {
  let fixture: ComponentFixture<Statistics>;
  afterEach(() => fixture?.destroy());

  const sample = (gpuFaults: string[] = []) => ({
    timestamp: '2026-10-12T07:49:00Z',
    scheduler_signals: { provider: { gpu_faults: gpuFaults, devices: [] } },
  });

  async function pageWith(providers: unknown[]) {
    const page = await pageAt();
    fixture = page.fx;
    (page.component as any).replaceRawVramSeries(providers);
    page.fx.detectChanges();
    return { component: page.component, el: page.fx.nativeElement as HTMLElement };
  }

  it('raises a failed GPU above the tabs, on the tab and on the worker row', async () => {
    const { component, el } = await pageWith([
      {
        provider_id: 1,
        name: 'deioma',
        connected: true,
        connection_state: 'online',
        data: [sample(['gpu0 (GPU-aaa): GPU requires reset'])],
      },
    ]);
    expect(component.gpuFaultCount()).toBe(1);
    expect(el.querySelector('.stats-gpu-fault')?.textContent).toContain('gpu0 (GPU-aaa): GPU requires reset');
    expect(el.querySelector('.stats-tabs__alert')?.textContent?.trim()).toBe('1');
    expect(el.querySelector('.stats-provider-badge--fault')?.textContent).toContain('1 GPU failed');

    // The banner stays on the Requests tab too.
    component.activeTab.set('requests');
    fixture.detectChanges();
    expect(el.querySelector('.stats-gpu-fault')).not.toBeNull();
  });

  it('folds an offline worker away behind a notice until asked for its last report', async () => {
    const { component, el } = await pageWith([
      {
        provider_id: 2,
        name: 'hochbrueck',
        connected: false,
        connection_state: 'offline',
        last_heartbeat: '2026-10-12T07:00:00Z',
        // A fault in a stale report is not raised: the GPU may have been reset since.
        data: [sample(['gpu0 (GPU-bbb): GPU requires reset'])],
      },
    ]);
    const row = el.querySelector('.stats-glass-row') as HTMLElement;
    expect(row.classList).toContain('stats-glass-row--offline');
    expect(row.querySelector('.stats-offline-notice')?.textContent).toContain('hochbrueck is offline.');
    expect(row.querySelector('.stats-panel-stack')).toBeNull();
    expect(component.gpuFaultCount()).toBe(0);

    (row.querySelector('.stats-offline-notice__toggle') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(row.querySelector('.stats-panel-stack--stale')).not.toBeNull();
  });

  it('shows the free disk space of each online worker in its row header', async () => {
    const disk = (freeMb: number) => ({
      timestamp: '2026-10-12T07:49:00Z',
      scheduler_signals: {
        provider: {
          devices: [],
          disk_total_mb: 2048 * 1024,
          disk_used_mb: 2048 * 1024 - freeMb,
          disk_free_mb: freeMb,
          disk_path: '/cache/.hf_cache',
        },
      },
    });
    const { el } = await pageWith([
      { provider_id: 1, name: 'deioma', connected: true, connection_state: 'online', data: [disk(412 * 1024)] },
      { provider_id: 2, name: 'gpu-full', connected: true, connection_state: 'online', data: [disk(10 * 1024)] },
      { provider_id: 3, name: 'hochbrueck', connected: false, connection_state: 'offline', data: [disk(900 * 1024)] },
    ]);
    const [deioma, full, offline] = Array.from(el.querySelectorAll('.stats-glass-row')) as HTMLElement[];
    const meter = deioma.querySelector('.stats-disk-meter') as HTMLElement;
    expect(meter.textContent).toContain('412 GB');
    expect(meter.textContent).toContain('free of 2.0 TB');
    expect(meter.title).toContain('/cache/.hf_cache');
    expect(meter.classList).not.toContain('stats-disk-meter--low');
    expect(full.querySelector('.stats-disk-meter')?.classList).toContain('stats-disk-meter--critical');
    // An offline worker's last reading may be long out of date.
    expect(offline.querySelector('.stats-disk-meter')).toBeNull();
  });
});
