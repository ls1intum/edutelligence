import { providerLabel } from '../../statistics.utils';

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
