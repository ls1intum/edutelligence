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
