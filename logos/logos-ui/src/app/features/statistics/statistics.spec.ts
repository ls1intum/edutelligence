import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { Statistics } from './statistics';
import { StatsWebsocketService } from './services/stats-websocket.service';
import { StatisticsService } from './services/statistics.service';

import type { TimelineRequestConfig } from './statistics.models';

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
describe('Statistics calendar rollover', () => {
  let fixture: ComponentFixture<Statistics> | undefined;

  const wsSpy = () => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    reconnect: vi.fn(),
    setTimelineRange: vi.fn(),
    setScope: vi.fn(),
    setFeedStatus: vi.fn(),
  });

  /** Boot the page at the frozen clock and wire in the service spies. */
  async function pageAt() {
    const ws = wsSpy();
    const getScopeOptions = vi.fn().mockResolvedValue({ teams: [], requesters: [] });
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
