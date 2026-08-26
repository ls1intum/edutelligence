import { SimpleChange } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RequestItem } from '../../../statistics/statistics.models';
import { ActivityFilter, TeamActivityService } from './activity-tab.service';
import { ActivityTabComponent } from './activity-tab';
import { TeamActivityPayload } from './activity-tab.models';

/** One unanswered service call, resolvable by the test in the order it wants. */
type Pending = {
  promise: Promise<TeamActivityPayload>;
  resolve: (payload: TeamActivityPayload) => void;
  answered: boolean;
};

function makePending(): Pending {
  let resolve!: (payload: TeamActivityPayload) => void;
  let answered = false;
  const promise = new Promise<TeamActivityPayload>((r) => {
    resolve = (payload: TeamActivityPayload) => {
      answered = true;
      r(payload);
    };
  });
  return { promise, resolve, get answered() { return answered; } };
}

/**
 * The Requests pager used to read its next cursor from whatever page answer
 * was still on screen. Press next while a page is loading and every extra
 * press advanced the index on that stale answer's strength — `has_more` and
 * the cursor both pointed at the page behind — until the page walked past
 * the last one (issue #799).
 *
 * These tests hold the service's answers in flight and turn the pages faster
 * than they land.
 */
describe('ActivityTabComponent pagination', () => {
  const PAGE_SIZE = 20;
  const TOTAL = 45; // two full pages and a short third, like the team in the report
  const LAST_PAGE = Math.ceil(TOTAL / PAGE_SIZE) - 1;

  let fixture: ComponentFixture<ActivityTabComponent>;
  let component: ActivityTabComponent;
  let service: { getActivity: ReturnType<typeof vi.fn> };
  let calls: Array<{ days: number; filter: ActivityFilter }>;
  let pending: Pending[];

  function row(n: number): RequestItem {
    return {
      request_id: `req-${n}`,
      model_name: 'gpt-5',
      provider_name: 'azure',
      is_cloud: true,
      status: 'success',
      timestamp: null,
      duration: null,
      cold_start: null,
      enqueue_ts: null,
      scheduled_ts: null,
      request_complete_ts: null,
      queue_seconds: null,
      total_seconds: null,
      initial_priority: null,
      priority_when_scheduled: null,
      queue_depth_at_enqueue: null,
      error_message: null,
      team_name: 'Logos',
      username: 'tobias.wasner',
      full_name: null,
      prompt_tokens: null,
      completion_tokens: null,
      total_tokens: null,
      cost_microcents: null,
    };
  }

  function rowsFor(pageIndex: number): RequestItem[] {
    const first = pageIndex * PAGE_SIZE + 1;
    const count = Math.min(PAGE_SIZE, TOTAL - first + 1);
    return Array.from({ length: count }, (_, i) => row(first + i));
  }

  function payload(rows: RequestItem[], hasNext: boolean): TeamActivityPayload {
    return {
      team_id: 28,
      days: 7,
      since: '2026-08-19T00:00:00Z',
      live: { queued: 0, running: 0, finished: TOTAL, failed: 0 },
      keys: [],
      total_tokens: 0,
      total_requests: TOTAL,
      requesters: [],
      requests: rows,
      requests_total: TOTAL,
      requests_has_more: hasNext,
      requests_next_cursor: hasNext
        ? { ts: '2026-08-19T12:00:00Z', request_id: rows[rows.length - 1].request_id }
        : null,
    };
  }

  /** Page `pageIndex` of the unfiltered list of TOTAL rows. */
  function pageFor(pageIndex: number): TeamActivityPayload {
    return payload(rowsFor(pageIndex), pageIndex < LAST_PAGE);
  }

  /** Let the component's continuation of a just-answered load settle. */
  function flush(): Promise<void> {
    return new Promise((r) => setTimeout(r, 0));
  }

  beforeEach(async () => {
    calls = [];
    pending = [];
    service = {
      getActivity: vi.fn(
        (_teamId: number, days: number, filter: ActivityFilter): Promise<TeamActivityPayload> => {
          calls.push({ days, filter });
          const call = makePending();
          pending.push(call);
          return call.promise;
        },
      ),
    };

    await TestBed.configureTestingModule({
      imports: [ActivityTabComponent],
      providers: [{ provide: TeamActivityService, useValue: service }],
    }).compileComponents();

    fixture = TestBed.createComponent(ActivityTabComponent);
    component = fixture.componentInstance;
    component.teamId = 28;
    component.ngOnChanges({ teamId: new SimpleChange(0, 28, false) });
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
  });

  it('walks the pages forward and back and stops at the last page', async () => {
    const first = pageFor(0);
    pending[0].resolve(first);
    await flush();

    expect(component.pageIndex()).toBe(0);
    expect(component.hasNext()).toBe(true);
    expect(component.pageLoadInFlight()).toBe(false);

    component.nextPage();
    // The second request goes out with the cursor the first page handed over.
    expect(calls[1].filter.cursor).toEqual(first.requests_next_cursor);

    pending[1].resolve(pageFor(1));
    await flush();

    expect(component.pageIndex()).toBe(1);
    expect(component.activity()?.requests.map((r) => r.request_id)).toEqual(
      rowsFor(1).map((r) => r.request_id),
    );
    expect(component.hasNext()).toBe(true);

    component.nextPage();
    pending[2].resolve(pageFor(2));
    await flush();

    expect(component.pageIndex()).toBe(LAST_PAGE);
    expect(component.hasNext()).toBe(false);
    expect(component.firstRowNumber()).toBe(LAST_PAGE * PAGE_SIZE + 1);
    expect(component.lastRowNumber()).toBe(TOTAL);

    // One more press on the last page changes nothing.
    component.nextPage();
    await flush();
    expect(component.pageIndex()).toBe(LAST_PAGE);
    expect(calls).toHaveLength(3);

    // Coming back is a pop of the stored cursor, not a new query.
    component.prevPage();
    expect(calls[3].filter.cursor).toEqual(first.requests_next_cursor);
    pending[3].resolve(pageFor(1));
    await flush();
    expect(component.pageIndex()).toBe(1);
    expect(component.activity()?.requests.map((r) => r.request_id)).toEqual(
      rowsFor(1).map((r) => r.request_id),
    );
  });

  it('ignores extra presses while a page is still loading', async () => {
    pending[0].resolve(pageFor(0));
    await flush();

    // Five rapid presses: every one after the first lands while the page is
    // still loading, which is how the index used to run past the end.
    for (let i = 0; i < 5; i++) {
      component.nextPage();
    }

    // The index is exactly one page ahead — no further — and the extra
    // presses did not queue extra requests.
    expect(component.pageIndex()).toBe(1);
    expect(component.pageLoadInFlight()).toBe(true);
    expect(calls).toHaveLength(2);

    pending[1].resolve(pageFor(1));
    await flush();

    expect(component.pageIndex()).toBe(1);
    expect(component.hasNext()).toBe(true);
    expect(component.pageLoadInFlight()).toBe(false);
  });

  it('lands on the last page and nowhere past it, however hard the presses come', async () => {
    pending[0].resolve(pageFor(0));
    await flush();

    // Keep pressing: the presses do not stop when the pages run out, they
    // just stop doing anything.
    for (let i = 0; i < 10; i++) {
      component.nextPage();
      const unanswered = pending.find((p) => !p.answered);
      if (!unanswered) break; // the pager stopped asking
      unanswered.resolve(pageFor(component.pageIndex()));
      await flush();
    }

    expect(component.pageIndex()).toBe(LAST_PAGE);
    expect(component.hasNext()).toBe(false);
    expect(component.firstRowNumber()).toBe(LAST_PAGE * PAGE_SIZE + 1);
    expect(component.lastRowNumber()).toBe(TOTAL);
    expect(calls).toHaveLength(LAST_PAGE + 1);
  });

  it('drops a stale page answer that lands after the list was refiltered', async () => {
    pending[0].resolve(pageFor(0));
    await flush();

    // A page turn goes in flight...
    component.nextPage();
    const pageTurn = pending[1];

    // ...and while it is out, the list narrows to one requester. The filter
    // restarts at page 0 with its own load.
    component.setRequester('42');
    const refilter = pending[2];
    expect(calls[2].filter.userId).toBe(42);
    expect(calls[2].filter.cursor).toBeNull();

    // The refiltered list is short: one page, and it is the last.
    const refiltered = payload(rowsFor(0), false);
    refilter.resolve(refiltered);
    await flush();

    // Now the old page turn arrives. Its rows and its has_more flag belong
    // to the list we left; neither may land on the new one.
    pageTurn.resolve(pageFor(1));
    await flush();

    expect(component.pageIndex()).toBe(0);
    expect(component.filterUserId()).toBe(42);
    expect(component.activity()).toBe(refiltered);
    expect(component.hasNext()).toBe(false);
    expect(component.pageLoadInFlight()).toBe(false);
  });

  it('disables the pager buttons while a page is loading', async () => {
    pending[0].resolve(pageFor(0));
    await flush();
    fixture.detectChanges();

    const [prevBtn, nextBtn] = fixture.nativeElement.querySelectorAll('.ac-pager__btn') as HTMLButtonElement[];
    expect(prevBtn.disabled).toBe(true); // first page
    expect(nextBtn.disabled).toBe(false);

    component.nextPage();
    fixture.detectChanges();
    expect(nextBtn.disabled).toBe(true); // in flight

    pending[1].resolve(pageFor(1));
    await flush();
    fixture.detectChanges();
    expect(prevBtn.disabled).toBe(false); // middle page: both ways open again
    expect(nextBtn.disabled).toBe(false);
  });
});
