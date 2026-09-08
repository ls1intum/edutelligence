import { SimpleChange } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { StatisticsService, RequestPayloads } from '../../services/statistics.service';
import { RequestItem } from '../../statistics.models';
import { RecentRequests } from './recent-requests';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => resolve = r);
  return { promise, resolve };
}

describe('Recent request payloads', () => {
  let component: RecentRequests;
  let getRequestPayloads: ReturnType<typeof vi.fn>;
  const row = { request_id: 'a' } as RequestItem;

  beforeEach(() => {
    getRequestPayloads = vi.fn();
    TestBed.configureTestingModule({
      providers: [{ provide: StatisticsService, useValue: { getRequestPayloads } }],
    });
    component = TestBed.runInInjectionContext(() => new RecentRequests());
  });
  afterEach(() => component.ngOnDestroy());

  it('loads only on demand and reuses content when switching tabs or reopening', async () => {
    const data = { input_payload: { messages: [{ content: '<script>text</script>' }] }, response_payload: 'data: chunk\n\ndata: [DONE]' };
    getRequestPayloads.mockResolvedValue(data);
    expect(getRequestPayloads).not.toHaveBeenCalled();
    component.togglePayloads(row);
    await Promise.resolve();
    expect(component.payloadText()).toContain('<script>text</script>');
    component.payloadTab.set('response');
    expect(component.payloadText()).toBe(data.response_payload);
    component.togglePayloads(row);
    component.togglePayloads(row);
    expect(getRequestPayloads).toHaveBeenCalledTimes(1);
  });

  it('keeps missing content distinct from empty content and can refresh a response', async () => {
    getRequestPayloads.mockResolvedValueOnce({ input_payload: '', response_payload: null })
      .mockResolvedValueOnce({ input_payload: '', response_payload: { answer: 42 } });
    await component.loadPayloads('a');
    expect(component.payloadText()).toBe('');
    component.payloadTab.set('response');
    expect(component.payloadText()).toBeNull();
    await component.loadPayloads('a');
    expect(component.payloadText()).toContain('42');
  });

  it('ignores an earlier request that finishes after selecting another row', async () => {
    const first = deferred<RequestPayloads>();
    getRequestPayloads.mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({ input_payload: 'B', response_payload: null });
    component.togglePayloads(row);
    component.togglePayloads({ request_id: 'b' } as RequestItem);
    await Promise.resolve();
    first.resolve({ input_payload: 'A', response_payload: null });
    await Promise.resolve();
    expect(component.payloadText()).toBe('B');
  });

  it('discards content arriving after a scope change', async () => {
    const pending = deferred<RequestPayloads>();
    getRequestPayloads.mockReturnValue(pending.promise);
    component.togglePayloads(row);
    component.filterTeamId = 2;
    component.ngOnChanges({ filterTeamId: new SimpleChange(1, 2, false) });
    pending.resolve({ input_payload: 'old team', response_payload: null });
    await Promise.resolve();
    expect(component.expandedRequestId()).toBeNull();
    expect(component.payloads()).toBeNull();
  });

  it('allows retrying a failed fetch', async () => {
    getRequestPayloads.mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ input_payload: 'retried', response_payload: null });
    await component.loadPayloads('a');
    expect(component.payloadError()).toBeTruthy();
    await component.loadPayloads('a');
    expect(component.payloadError()).toBeNull();
    expect(component.payloadText()).toBe('retried');
  });
});
