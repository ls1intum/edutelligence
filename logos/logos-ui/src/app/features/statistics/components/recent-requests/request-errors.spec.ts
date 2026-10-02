import { ComponentFixture, TestBed } from '@angular/core/testing';
import { StatisticsService } from '../../services/statistics.service';
import { RequestItem } from '../../statistics.models';
import { RecentRequests } from './recent-requests';

describe('Recent request errors', () => {
  let fixture: ComponentFixture<RecentRequests>;
  let getRequestPayloads: ReturnType<typeof vi.fn>;
  const message =
    'The provider could not complete this request because the model exceeded its context window.\n' +
    '<script>Provider details must remain plain text.</script> Retry with a shorter prompt.';
  const failedRequest: RequestItem = {
    request_id: 'failed-request',
    model_name: 'model-a',
    provider_name: 'cloud-provider',
    is_cloud: true,
    status: 'error',
    timestamp: '2026-09-30T10:00:00Z',
    duration: 1,
    cold_start: false,
    enqueue_ts: '2026-09-30T10:00:00Z',
    scheduled_ts: '2026-09-30T10:00:01Z',
    request_complete_ts: '2026-09-30T10:00:02Z',
    queue_seconds: 1,
    total_seconds: 2,
    initial_priority: null,
    priority_when_scheduled: null,
    queue_depth_at_enqueue: null,
    error_message: message,
    team_name: null,
    username: null,
    full_name: null,
    api_key_name: null,
    api_key_type: null,
    environment: null,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    cost_microcents: null,
  };

  beforeEach(async () => {
    getRequestPayloads = vi.fn();
    await TestBed.configureTestingModule({
      imports: [RecentRequests],
      providers: [{ provide: StatisticsService, useValue: { getRequestPayloads } }],
    }).compileComponents();
    fixture = TestBed.createComponent(RecentRequests);
    setRequests([failedRequest]);
  });

  afterEach(() => fixture.destroy());

  function setRequests(requests: RequestItem[]): void {
    fixture.componentRef.setInput('liveRequests', requests);
    fixture.detectChanges();
  }

  function errorDetails(): HTMLDetailsElement {
    return fixture.nativeElement.querySelector('.rr-card__error');
  }

  it('keeps the complete message in the preview and hover text instead of cutting it at 60 characters', () => {
    const details = errorDetails();
    expect(details.open).toBe(false);
    expect(details.querySelector('.rr-card__error-snippet')?.textContent?.trim()).toBe(message);
    expect(details.querySelector('summary')?.title).toBe(message);
  });

  it('expands and collapses the full multiline error as plain text without fetching request content', () => {
    const details = errorDetails();
    const summary = details.querySelector('summary')!;
    summary.click();
    expect(details.open).toBe(true);
    expect(details.querySelector('.rr-card__error-message')?.textContent?.trim()).toBe(message);
    expect(details.querySelector('script')).toBeNull();
    expect(getRequestPayloads).not.toHaveBeenCalled();
    summary.click();
    expect(details.open).toBe(false);
  });

  it('keeps an expanded error open when the live feed updates the same request', () => {
    const details = errorDetails();
    details.querySelector('summary')!.click();
    const updatedMessage = `${message}\nAdditional provider diagnostics.`;
    setRequests([{ ...failedRequest, error_message: updatedMessage }]);
    expect(errorDetails().open).toBe(true);
    expect(errorDetails().querySelector('.rr-card__error-message')?.textContent?.trim()).toBe(
      updatedMessage,
    );
  });

  it('shows error details only for completed failed requests with a message', () => {
    setRequests([
      failedRequest,
      { ...failedRequest, request_id: 'no-message', error_message: null },
      { ...failedRequest, request_id: 'successful', status: 'success' },
      { ...failedRequest, request_id: 'running', request_complete_ts: null },
    ]);
    expect(fixture.nativeElement.querySelectorAll('.rr-card__error')).toHaveLength(1);
  });
});
