import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

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
});

/** Boot the page at the frozen clock and wire in the service spies. */
async function pageAt(
  getScopeOptions: ReturnType<typeof vi.fn> = vi.fn().mockResolvedValue({
    teams: [],
    requesters: [],
  }),
) {
  const ws = wsSpy();
  await TestBed.configureTestingModule({
    imports: [Statistics],
    providers: [
      { provide: StatsWebsocketService, useValue: ws },
      { provide: StatisticsService, useValue: { getScopeOptions } },
    ],
  }).compileComponents();
  const fx = TestBed.createComponent(Statistics);
  const component = fx.componentInstance;
  component.ngOnInit();
  return { fx, component, ws, getScopeOptions };
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
    const rangesBefore = page.ws.setTimelineRange.mock.calls.length;

    // 23:50 to 23:59, still the same day: every tick is a no-op.
    vi.advanceTimersByTime(9 * 60_000);

    expect(page.ws.setTimelineRange.mock.calls.length).toBe(rangesBefore);
    // The page is up and connected, so the silence is a decision, not an absence.
    expect(page.ws.connect).toHaveBeenCalledTimes(1);
  });

  it('re-anchors the range at each midnight while the page stays open', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 6, 23, 50, 0, 0));
    const page = await pageAt();
    fixture = page.fx;

    page.component.setPreset('day');
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
    let releaseStale: (value: { teams: FeedFilterOption[]; requesters: FeedFilterOption[] }) => void =
      () => {};
    const stale = new Promise<{ teams: FeedFilterOption[]; requesters: FeedFilterOption[] }>(
      (resolve) => {
        releaseStale = resolve;
      },
    );
    const fresh: { teams: FeedFilterOption[]; requesters: FeedFilterOption[] } = {
      teams: [{ id: 1, label: 'Team One', requestCount: 3 }],
      requesters: [{ id: 7, label: 'User Seven', requestCount: 5 }],
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
    page.component.setUserFilter('7');
    await Promise.resolve();
    await Promise.resolve();
    const scopesBefore = page.ws.setScope.mock.calls.length;

    // The stale response lands last: empty lists, no user 7.
    releaseStale({ teams: [], requesters: [] });
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
    let releaseStale: (value: { teams: FeedFilterOption[]; requesters: FeedFilterOption[] }) => void =
      () => {};
    const stale = new Promise<{ teams: FeedFilterOption[]; requesters: FeedFilterOption[] }>(
      (resolve) => {
        releaseStale = resolve;
      },
    );
    const fresh: { teams: FeedFilterOption[]; requesters: FeedFilterOption[] } = {
      teams: [{ id: 1, label: 'Team One', requestCount: 3 }],
      requesters: [{ id: 7, label: 'User Seven', requestCount: 5 }],
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

    page.component.setUserFilter('7');
    await Promise.resolve();
    await Promise.resolve();
    const scopesBefore = page.ws.setScope.mock.calls.length;

    releaseStale({ teams: [], requesters: [] });
    await Promise.resolve();
    await Promise.resolve();

    expect(page.component.feedUsers()).toEqual(fresh.requesters);
    expect(page.component.feedTeams()).toEqual(fresh.teams);
    expect(page.component.filterUserId()).toBe(7);
    expect(page.ws.setScope.mock.calls.length).toBe(scopesBefore);
  });
});
