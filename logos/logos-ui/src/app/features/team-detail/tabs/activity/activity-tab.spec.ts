import { SimpleChange } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RequestItem } from '../../../statistics/statistics.models';
import { TeamActivityPayload } from './activity-tab.models';
import { ActivityTabComponent } from './activity-tab';
import { TeamActivityService } from './activity-tab.service';

/**
 * The team activity view app administrators asked for (issue #776).
 *
 * The numbers it shows are load-bearing in both directions: the live tiles
 * tell an owner whether the cluster is working for them right now, and the
 * per-key table tells them where the tokens went. A drift in either reading —
 * an in-flight count that double-counts, a token total that renders a
 * nine-digit number without abbreviation, a filter that widens past the team —
 * would make an owner misread what their team is doing.
 */

const makeRequest = (overrides: Partial<RequestItem> = {}): RequestItem => ({
  request_id: 'req-1',
  model_name: 'gpt-test',
  provider_name: 'test-provider',
  is_cloud: null,
  status: 'success',
  timestamp: '2026-08-26T12:00:00Z',
  duration: null,
  cold_start: null,
  enqueue_ts: '2026-08-26T12:00:00Z',
  scheduled_ts: null,
  request_complete_ts: null,
  queue_seconds: null,
  total_seconds: null,
  initial_priority: null,
  priority_when_scheduled: null,
  queue_depth_at_enqueue: null,
  error_message: null,
  team_name: null,
  username: 'test.user',
  full_name: 'Test User',
  prompt_tokens: null,
  completion_tokens: null,
  total_tokens: null,
  cost_microcents: null,
  ...overrides,
});

const makePayload = (overrides: Partial<TeamActivityPayload> = {}): TeamActivityPayload => ({
  team_id: 2001,
  days: 7,
  since: '2026-08-19T12:00:00Z',
  live: { queued: 0, running: 0, finished: 0, failed: 0 },
  keys: [],
  total_tokens: 0,
  total_requests: 0,
  requesters: [],
  requests: [makeRequest()],
  requests_total: 1,
  requests_has_more: true,
  requests_next_cursor: { ts: '2026-08-26T12:00:00Z', request_id: 'req-1' },
  ...overrides,
});

describe('ActivityTabComponent', () => {
  let fixture: ComponentFixture<ActivityTabComponent>;
  let component: ActivityTabComponent;
  const getActivity = vi.fn();

  beforeEach(async () => {
    vi.clearAllMocks();
    getActivity.mockResolvedValue(makePayload());

    await TestBed.configureTestingModule({
      imports: [ActivityTabComponent],
      providers: [{ provide: TeamActivityService, useValue: { getActivity } }],
    }).compileComponents();

    fixture = TestBed.createComponent(ActivityTabComponent);
    component = fixture.componentInstance;
  });

  afterEach(() => {
    // The tab polls on its own while mounted; drop the interval so no test
    // keeps a timer alive past the one that started it.
    component.ngOnDestroy();
  });

  /** Mount the tab for one team and wait for the first load to settle. */
  const loadForTeam = async (): Promise<void> => {
    component.teamId = 2001;
    component.ngOnChanges({ teamId: new SimpleChange(0, 2001, true) });
    await vi.waitFor(() => expect(getActivity).toHaveBeenCalledTimes(1));
  };

  // ── Reading the numbers ────────────────────────────────────────────────────

  describe('formatTokens', () => {
    it('shows nothing for a team that used nothing', () => {
      // The payload says zero and the server also sends null for a key whose
      // requests recorded no usage — both must read as "0", never blank.
      expect(component.formatTokens(0)).toBe('0');
      expect(component.formatTokens(null)).toBe('0');
      expect(component.formatTokens(undefined)).toBe('0');
    });

    it('keeps exact counts while they fit on one screen', () => {
      expect(component.formatTokens(999)).toBe('999');
    });

    it('abbreviates the totals that run past it', () => {
      // A busy team clears nine figures over a quarter; the tile holds a
      // figure plus a suffix, not ten digits.
      expect(component.formatTokens(1_500)).toBe('1.5k');
      expect(component.formatTokens(1_234_567)).toBe('1.2M');
      expect(component.formatTokens(2_500_000_000)).toBe('2.5B');
    });
  });

  describe('keyLabel', () => {
    it('drops the environment placeholder the database carries', () => {
      // Keys without an environment store "-", and "dev key · -" would read
      // as a broken row to the owner.
      expect(component.keyLabel('dev key', '-')).toBe('dev key');
      expect(component.keyLabel('dev key', null)).toBe('dev key');
    });

    it('shows the environment when it is real', () => {
      expect(component.keyLabel('dev key', 'prod')).toBe('dev key · prod');
    });
  });

  describe('live figures', () => {
    it('adds queued and running into the in-flight number', () => {
      // The "Nothing of this team's is in the cluster" note keys on exactly
      // this sum — finished belongs to the period, not to right now.
      component.activity.set(
        makePayload({ live: { queued: 2, running: 3, finished: 10, failed: 1 } }),
      );
      expect(component.inFlight()).toBe(5);
    });

    it('is zero before the first payload arrives', () => {
      expect(component.inFlight()).toBe(0);
    });

    it('measures the failure rate against finished', () => {
      // The rate answers "of what got through, how much broke" — dividing by
      // the in-flight count would swing it with every request that starts.
      component.activity.set(
        makePayload({ live: { queued: 0, running: 0, finished: 100, failed: 25 } }),
      );
      expect(component.failureRate()).toBeCloseTo(25);
    });

    it('has no rate to show while nothing finished', () => {
      // 1/0 is not a rate; the tile then shows the plain note instead.
      component.activity.set(
        makePayload({ live: { queued: 4, running: 1, finished: 0, failed: 0 } }),
      );
      expect(component.failureRate()).toBeNull();
    });
  });

  describe('requester options', () => {
    it('offers everyone first, then each requester with its count', () => {
      // The count is what tells the owner which entry is worth opening; the
      // empty entry is the way back out of a filter.
      component.activity.set(
        makePayload({ requesters: [{ id: 11, label: 'Test User', requestCount: 40 }] }),
      );
      expect(component.requesterOptions()).toEqual([
        { value: '', label: 'Everyone in this team' },
        { value: '11', label: 'Test User (40)' },
      ]);
    });
  });

  // ── Loading ────────────────────────────────────────────────────────────────

  describe('loading', () => {
    it('loads for the team it belongs to, on the default window', async () => {
      await loadForTeam();
      expect(getActivity).toHaveBeenCalledWith(2001, 7, { userId: null, cursor: null });
      expect(component.loading()).toBe(false);
    });

    it('keeps the last good payload when a refresh fails', async () => {
      // The refresh runs on a timer: blanking the tab over one failed poll
      // would make a network blip look like an outage.
      await loadForTeam();
      const first = component.activity();

      getActivity.mockRejectedValueOnce(new Error('poll failed'));
      await component.setDays('30');

      expect(component.activity()).toBe(first);
      expect(component.error()).toBe('Could not refresh activity.');
      expect(component.loading()).toBe(false);
    });
  });

  // ── Window and filter ──────────────────────────────────────────────────────

  describe('window', () => {
    it('switches the window and starts the request pages over', async () => {
      // A different window is a different set of requests, so the cursors of
      // the old one no longer point anywhere — page 2 of 7 days is not page 2
      // of 30 days.
      await loadForTeam();
      await component.nextPage();
      expect(component.pageIndex()).toBe(1);

      await component.setDays('30');

      expect(getActivity).toHaveBeenLastCalledWith(2001, 30, { userId: null, cursor: null });
      expect(component.pageIndex()).toBe(0);
    });

    it('ignores a window it cannot use', () => {
      component.setDays('0');
      component.setDays('abc');
      component.setDays(null);
      expect(component.days()).toBe(7);
      expect(getActivity).not.toHaveBeenCalled();
    });
  });

  describe('requester filter', () => {
    it('narrows the request list to one requester', async () => {
      await loadForTeam();
      await component.setRequester('11');
      expect(getActivity).toHaveBeenLastCalledWith(2001, 7, { userId: 11, cursor: null });
    });

    it('treats the empty pick as no filter', async () => {
      await loadForTeam();
      await component.setRequester('11');
      await component.setRequester('');
      expect(getActivity).toHaveBeenLastCalledWith(2001, 7, { userId: null, cursor: null });
    });

    it('does not reload while the pick is unchanged', async () => {
      await loadForTeam();
      await component.setRequester('11');
      expect(getActivity).toHaveBeenCalledTimes(2);
      await component.setRequester('11');
      expect(getActivity).toHaveBeenCalledTimes(2);
    });
  });

  // ── Request pages ──────────────────────────────────────────────────────────

  describe('request pages', () => {
    it('walks the cursor one page at a time and back', async () => {
      await loadForTeam();

      await component.nextPage();
      expect(component.pageIndex()).toBe(1);
      expect(getActivity).toHaveBeenLastCalledWith(2001, 7, {
        userId: null,
        cursor: { ts: '2026-08-26T12:00:00Z', request_id: 'req-1' },
      });

      await component.prevPage();
      expect(component.pageIndex()).toBe(0);
      expect(getActivity).toHaveBeenLastCalledWith(2001, 7, { userId: null, cursor: null });
    });

    it('does not step past the last page', async () => {
      component.teamId = 2001;
      component.activity.set(makePayload({ requests_has_more: false, requests_next_cursor: null }));

      await component.nextPage();

      expect(component.pageIndex()).toBe(0);
      expect(getActivity).not.toHaveBeenCalled();
    });

    it('numbers the rows of the page it shows', () => {
      component.pageIndex.set(1);
      component.activity.set(
        makePayload({
          requests: Array.from({ length: 20 }, (_, i) =>
            makeRequest({ request_id: `req-${i + 1}` }),
          ),
        }),
      );
      // The "21-40 of n" line: one-based, page 0 is the newest rows.
      expect(component.firstRowNumber()).toBe(21);
      expect(component.lastRowNumber()).toBe(40);
    });
  });

  // ── Request rows ───────────────────────────────────────────────────────────

  describe('request rows', () => {
    it('shows prompt and completion tokens as up and down', () => {
      expect(component.tokensOf(makeRequest({ prompt_tokens: 120, completion_tokens: 480 }))).toBe(
        '↑120 ↓480',
      );
    });

    it('shows nothing a request did not record', () => {
      // Failed before the first chunk never carried usage — "—" is the honest
      // cell, 0 would claim the model used no tokens.
      expect(
        component.tokensOf(makeRequest({ prompt_tokens: null, completion_tokens: null })),
      ).toBe('—');
    });

    it('shows the wall-clock duration when it is known', () => {
      expect(component.durationOf(makeRequest({ total_seconds: 3.14 }))).toBe('3.14s');
      expect(component.durationOf(makeRequest({ total_seconds: null }))).toBe('—');
    });

    it('reads the stage off the timestamps, not a status flag', () => {
      // The server sends no stage column; the timestamps are what separates
      // queued from executing from complete.
      expect(component.stageOf(makeRequest())).toBe('queued');
      expect(component.stageOf(makeRequest({ scheduled_ts: '2026-08-26T12:00:05Z' }))).toBe(
        'executing',
      );
      expect(
        component.stageOf(
          makeRequest({
            scheduled_ts: '2026-08-26T12:00:05Z',
            request_complete_ts: '2026-08-26T12:00:30Z',
          }),
        ),
      ).toBe('complete');
    });

    it('shows the full name, falling back to the username', () => {
      expect(component.requesterOf(makeRequest())).toBe('Test User');
      expect(component.requesterOf(makeRequest({ full_name: '   ' }))).toBe('test.user');
    });
  });
});
