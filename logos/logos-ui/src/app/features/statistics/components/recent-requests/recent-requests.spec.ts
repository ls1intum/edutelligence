import { SimpleChange } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { providerLabel } from '../../statistics.utils';
import { RequestItem } from '../../statistics.models';
import { StatisticsService } from '../../services/statistics.service';
import { chaseStep, tokenLabel, RecentRequests } from './recent-requests';

/**
 * The provider label of a request row.
 *
 * The log row carries a provider from the moment it is enqueued — the
 * deployment the request was made for, not the one that will serve it. While
 * the request is still queued at the orchestrator nothing has been forwarded
 * anywhere, so naming a provider would show a decision that has not been made
 * yet, and a row whose provider changes at the end must be able to grow into
 * the real one rather than keeping the early guess.
 */
describe('providerLabel', () => {
  it('says none while the request is still queued, even though a provider is on the row', () => {
    // The enqueue-time write already recorded the deployment the request was
    // made for — the very figure the row must not show before forwarding.
    expect(
      providerLabel({
        provider_name: 'gpu-01',
        scheduled_ts: null,
        request_complete_ts: null,
      }),
    ).toBe('none');
  });

  it('shows the provider once the request has been forwarded', () => {
    expect(
      providerLabel({
        provider_name: 'gpu-02',
        scheduled_ts: '2026-08-28T10:15:30Z',
        request_complete_ts: null,
      }),
    ).toBe('gpu-02');
  });

  it('shows the provider of a settled row', () => {
    expect(
      providerLabel({
        provider_name: 'azure-openai',
        scheduled_ts: '2026-08-28T10:15:30Z',
        request_complete_ts: '2026-08-28T10:15:42Z',
      }),
    ).toBe('azure-openai');
  });

  it('falls back to none for a settled row without a provider of its own', () => {
    // A request that failed before anything was scheduled has a terminal
    // state but never a forwarding — its row has no provider to name.
    expect(
      providerLabel({
        provider_name: null,
        scheduled_ts: null,
        request_complete_ts: '2026-08-28T10:15:42Z',
      }),
    ).toBe('none');
    expect(
      providerLabel({
        provider_name: '',
        scheduled_ts: '2026-08-28T10:15:30Z',
        request_complete_ts: null,
      }),
    ).toBe('none');
  });
});

/**
 * The count-up behind the live token line.
 *
 * A push lands a new target; between pushes the figure on screen moves part of
 * the way there every frame, so a jump of nine tokens reads as motion instead
 * of a teleport.
 */
describe('chaseStep', () => {
  it('stays put when the target has not moved', () => {
    expect(chaseStep(42, 42)).toBe(42);
  });

  it('closes 30% of the gap per frame, at least one token', () => {
    expect(chaseStep(0, 10)).toBe(3);
    expect(chaseStep(3, 10)).toBe(6);
    expect(chaseStep(6, 10)).toBe(8);
    expect(chaseStep(8, 10)).toBe(9);
  });

  it('reaches the target in the frame that would overshoot it', () => {
    expect(chaseStep(9, 10)).toBe(10);
    expect(chaseStep(0, 1)).toBe(1);
  });

  it('runs a long queue of growth out in a handful of frames', () => {
    // 1200 tokens: the first frame already takes a third of the way.
    let n = 0;
    for (let i = 0; i < 50 && n < 1200; i++) n = chaseStep(n, 1200);
    expect(n).toBe(1200);
  });

  it('snaps to a lower target instead of counting backwards', () => {
    // The estimate the real prompt replaced: 1200 down to 1187. A backwards
    // count-up would read as the number falling out of the air.
    expect(chaseStep(1200, 1187)).toBe(1187);
  });
});

describe('tokenLabel', () => {
  const shown = { p: 1200, c: 42 };

  it('shows nothing when neither figure is known', () => {
    expect(tokenLabel(null, null, shown, false)).toBeNull();
  });

  it('shows the figures the row is displaying, padded with zero', () => {
    expect(tokenLabel(1200, 42, shown, false)).toBe('↑1200 ↓42');
    expect(tokenLabel(null, 42, { p: 0, c: 42 }, false)).toBe('↑0 ↓42');
  });

  it('marks a prompt the upstream has not stated yet', () => {
    // The request still queues; 1200 is what the body looks like in tokens,
    // not what a model counted. The tilde keeps the page honest about that.
    expect(tokenLabel(1200, 0, { p: 1200, c: 0 }, true)).toBe('↑~1200 ↓0');
    expect(tokenLabel(1200, 0, { p: 1200, c: 0 }, false)).toBe('↑1200 ↓0');
  });
});

/**
 * The "of N" figure while a state-filtered feed waits for the first push of
 * its own bucket total.
 *
 * The page passes `null` for totalInRange in that window: the KPI aggregate
 * it would otherwise borrow describes the whole scope, not the bucket, so the
 * header must have no figure at all rather than one for a different set.
 */
describe('totalCount for a filtered feed without a bucket total yet', () => {
  const settledRow: RequestItem = {
    request_id: 'req-feed-total',
    model_name: 'model-a',
    provider_name: 'gpu-01',
    is_cloud: false,
    status: 'success',
    timestamp: '2026-08-29T10:00:00Z',
    duration: 12,
    cold_start: false,
    enqueue_ts: '2026-08-29T10:00:00Z',
    scheduled_ts: '2026-08-29T10:00:01Z',
    request_complete_ts: '2026-08-29T10:00:13Z',
    queue_seconds: 1,
    total_seconds: 13,
    initial_priority: 'normal',
    priority_when_scheduled: 'normal',
    queue_depth_at_enqueue: 0,
    error_message: null,
    team_name: 'Team 1',
    username: 'operator',
    full_name: 'The Operator',
    prompt_tokens: 1200,
    completion_tokens: 42,
    total_tokens: 1242,
    cost_microcents: 123,
  };

  let component: RecentRequests;

  async function createComponent(totalInRange: number | null): Promise<RecentRequests> {
    await TestBed.configureTestingModule({
      imports: [RecentRequests],
      providers: [{ provide: StatisticsService, useValue: {} }],
    }).compileComponents();
    const fixture: ComponentFixture<RecentRequests> = TestBed.createComponent(RecentRequests);
    component = fixture.componentInstance;
    component.totalInRange = totalInRange;
    component.liveRequests = [settledRow];
    component.ngOnChanges({
      totalInRange: new SimpleChange(0, totalInRange, true),
      liveRequests: new SimpleChange([], [settledRow], true),
    });
    fixture.detectChanges();
    return component;
  }

  afterEach(() => {
    // The toolbar runs its own ticker and the token line its own chase; drop
    // both so no test keeps a timer alive past the one that started it.
    component.ngOnDestroy();
  });

  it('has no figure at all, so the header can show "—" instead of a wrong one', async () => {
    expect((await createComponent(null)).totalCount()).toBeNull();
  });

  it('shows the bucket total once the first push for it lands', async () => {
    expect((await createComponent(7)).totalCount()).toBe(7);
  });
});
