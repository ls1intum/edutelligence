import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { StatisticsService } from './statistics.service';

describe('request feed REST filters', () => {
  it('sends all filter dimensions and the keyset cursor together', async () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const http = TestBed.inject(HttpTestingController);
    const page = TestBed.inject(StatisticsService).getLatestRequests(
      'start',
      'end',
      10,
      {
        userId: 1,
        teamId: 2,
        providerId: 3,
        apiKeyId: 7,
        errorsOnly: true,
        status: 'error',
        modelIds: [4, 5],
        providerIds: [3, 6],
      },
      { ts: 'cursor-time', request_id: 'cursor-request' },
    );
    const request = http.expectOne('/api/logosdb/latest_requests');
    expect(request.request.body).toEqual({
      start: 'start',
      end: 'end',
      limit: 10,
      user_id: 1,
      team_id: 2,
      provider_id: 3,
      api_key_id: 7,
      errors_only: true,
      status: 'error',
      model_ids: [4, 5],
      provider_ids: [3, 6],
      cursor_ts: 'cursor-time',
      cursor_id: 'cursor-request',
    });
    request.flush({ requests: [], total: 0, has_more: false, next_cursor: null });
    expect((await page).total).toBe(0);
    http.verify();
  });
});

describe('maintenance API', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
  });

  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('reads maintenance status through the webservice route', async () => {
    const http = TestBed.inject(HttpTestingController);
    const result = TestBed.inject(StatisticsService).getMaintenanceStatus();
    const request = http.expectOne('/api/logosdb/maintenance');
    expect(request.request.method).toBe('GET');
    const status = { free: true, limit: 1, calibrations: [], benchmarks: [], recoveries: [] };
    request.flush(status);
    expect(await result).toEqual(status);
  });

  it('releases a calibration claim through the webservice route', async () => {
    const http = TestBed.inject(HttpTestingController);
    const result = TestBed.inject(StatisticsService).releaseCalibrationClaim(12, 'claim-1');
    const request = http.expectOne('/api/logosdb/maintenance/release_calibration');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ provider_id: 12, claim_token: 'claim-1' });
    request.flush({ released: true, forced: false });
    expect(await result).toEqual({ released: true, forced: false });
  });

  it.each([false, true])('posts the deployment and force=%s', async (force) => {
    const http = TestBed.inject(HttpTestingController);
    const result = TestBed.inject(StatisticsService).releaseRecovery(31, force);
    const request = http.expectOne('/api/logosdb/maintenance/release_recovery');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ model_provider_id: 31, force });
    request.flush({ released: true, forced: force });
    expect((await result).forced).toBe(force);
  });
});
