import { providerLabel } from '../../statistics.utils';
import { chaseStep, tokenLabel } from './recent-requests';

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
