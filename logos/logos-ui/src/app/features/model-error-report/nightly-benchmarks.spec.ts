import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { NightlyBenchmarks } from './nightly-benchmarks';

describe('Nightly benchmark confirmation', () => {
  let control: NightlyBenchmarks;
  let http: HttpTestingController;
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    control = TestBed.runInInjectionContext(() => new NightlyBenchmarks());
    control.pairId = 31;
    control.providerName = 'Worker A';
    control.state.set({ enabled: false, status: 'disabled', report: [], recovery_required: false,
      window: { start: '05:00', end: '08:00', benchmark_start_cutoff: '07:50', timezone: 'Europe/Berlin' } });
  });
  afterEach(() => { control.ngOnDestroy(); http.verify(); });

  it('explains worker reservation and restoration', () => {
    expect(control.confirmationMessage).toContain('cannot serve production requests');
    expect(control.confirmationMessage).toContain('Original settings are restored');
  });

  it('does not activate with missing server window settings', () => {
    control.state.set({ enabled: false, status: 'disabled', report: [], recovery_required: false });
    control.review();
    expect(control.confirming()).toBe(false);
    http.expectNone('/api/logosdb/model_benchmarks/nightly/configure');
  });

  it('requires confirmation to enable and disable', async () => {
    await control.confirm();
    http.expectNone('/api/logosdb/model_benchmarks/nightly/configure');
    control.review();
    expect(control.confirming()).toBe(true);
    http.expectNone('/api/logosdb/model_benchmarks/nightly/configure');
    const first = control.confirm();
    const enable = http.expectOne('/api/logosdb/model_benchmarks/nightly/configure');
    expect(enable.request.body).toEqual({ model_provider_id: 31, enabled: true, expected_enabled: false });
    enable.flush({ enabled: true, status: 'scheduled', report: [], recovery_required: false });
    await first;
    expect(control.state()!.enabled).toBe(true);
    control.review();
    expect(control.enabling).toBe(false);
    const second = control.confirm();
    const disable = http.expectOne('/api/logosdb/model_benchmarks/nightly/configure');
    expect(disable.request.body.enabled).toBe(false);
    disable.flush({ enabled: false, status: 'disabled', report: [], recovery_required: false });
    await second;
    expect(control.state()!.enabled).toBe(false);
  });

  it('does not change the saved state on cancellation or server failure', async () => {
    control.review();
    control.confirming.set(false);
    await control.confirm();
    http.expectNone('/api/logosdb/model_benchmarks/nightly/configure');
    control.review();
    const pending = control.confirm();
    http.expectOne('/api/logosdb/model_benchmarks/nightly/configure').flush({ detail: 'State changed' }, { status: 409, statusText: 'Conflict' });
    await pending;
    expect(control.state()!.enabled).toBe(false);
    expect(control.error()).toBe('State changed');
    expect(control.confirming()).toBe(true);
  });

  it('submits once while saving and rejects stale polling state', async () => {
    const refresh = control.refresh();
    const poll = http.expectOne('/api/logosdb/model_benchmarks/nightly/status');
    control.review();
    const pending = control.confirm();
    await control.confirm();
    const request = http.expectOne('/api/logosdb/model_benchmarks/nightly/configure');
    request.flush({ enabled: true, status: 'scheduled', report: [], recovery_required: false });
    await pending;
    poll.flush({ enabled: false, status: 'disabled', report: [], recovery_required: false });
    await refresh;
    expect(control.state()!.enabled).toBe(true);
  });
});

describe('Shared maintenance window display', () => {
  it('uses the server window in confirmations and cutoff labels', () => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const control = TestBed.runInInjectionContext(() => new NightlyBenchmarks());
    control.state.set({ enabled: false, status: 'disabled', report: [], recovery_required: false,
      window: { start: '06:00', end: '09:00', benchmark_start_cutoff: '08:50', timezone: 'UTC' } });
    control.review();
    expect(control.confirmationMessage).toContain('06:00–09:00 UTC');
    expect(control.statusLabel('window_closed')).toContain('08:50');
    expect(control.statusLabel('window_closed_below_half')).toContain('09:00');
    control.ngOnDestroy();
  });
});
