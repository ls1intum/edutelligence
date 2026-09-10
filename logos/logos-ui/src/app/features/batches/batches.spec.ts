import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { Batches } from './batches';
import { BatchObject } from '../../core/services/batch.service';

/**
 * The page's own judgements: what counts as finished, and how much of a batch
 * has been done. Both drive the poll loop and the buttons, so they are worth
 * pinning down independently of the template.
 */

const batch = (overrides: Partial<BatchObject> = {}): BatchObject => ({
  id: 'batch_1',
  object: 'batch',
  status: 'in_progress',
  endpoint: '/v1/chat/completions',
  input_file_id: 'file-in',
  output_file_id: null,
  created_at: 0,
  completed_at: null,
  ...overrides,
});

describe('Batches', () => {
  let page: Batches;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    page = TestBed.runInInjectionContext(() => new Batches());
  });

  it('treats every state the job will not leave on its own as terminal', () => {
    for (const status of ['completed', 'failed', 'expired', 'cancelled']) {
      expect(page.isTerminal(batch({ status }))).toBe(true);
    }
    for (const status of ['validating', 'in_progress', 'cancelling', 'finalizing']) {
      expect(page.isTerminal(batch({ status }))).toBe(false);
    }
  });

  it('keeps polling only while something is still moving', () => {
    page.batches.set([batch({ status: 'completed' }), batch({ id: 'b2', status: 'in_progress' })]);
    expect(page.hasRunning()).toBe(true);

    page.batches.set([batch({ status: 'completed' })]);
    expect(page.hasRunning()).toBe(false);
  });

  it('counts failed requests as done, and says how many failed', () => {
    expect(page.progressOf(batch({ request_counts: { total: 10, completed: 6, failed: 2 } })))
      .toBe('8 / 10 (2 failed)');
    expect(page.progressOf(batch({ request_counts: { total: 10, completed: 10, failed: 0 } })))
      .toBe('10 / 10');
    // A forwarded batch reports no counts until the provider does.
    expect(page.progressOf(batch())).toBe('—');
  });
});
