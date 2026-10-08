import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { PublicStatsService, PublicStats } from './public-stats.service';

function payload(overrides: Partial<PublicStats> = {}): PublicStats {
  return {
    days: '30',
    students: 5,
    teams: 2,
    successful_requests: 5,
    average_requests_per_user: 1.2,
    requests_per_team: [{ team_id: 1, team_name: 'Team', requests: 5 }],
    requests_by_key_type: { developer: 3, application: 2, service: 0 },
    local_cloud_requests: { local: 1, cloud: 4 },
    ...overrides,
  };
}

describe('PublicStatsService', () => {
  function serviceAndHttp(): { service: PublicStatsService; http: HttpTestingController } {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    return { service: TestBed.inject(PublicStatsService), http: TestBed.inject(HttpTestingController) };
  }

  it('reads the aggregates from the unauthenticated public endpoint with default days=30', async () => {
    const { service, http } = serviceAndHttp();
    const pending = service.getStats();
    const request = http.expectOne(
      (req) => req.url === '/api/public/stats' && req.method === 'GET' && req.params.get('days') === '30'
    );
    const body = payload();
    request.flush(body);
    await expect(pending).resolves.toEqual(body);
    http.verify();
  });

  it('forwards the selected days window', async () => {
    const { service, http } = serviceAndHttp();
    const pending = service.getStats('7');
    const request = http.expectOne(
      (req) => req.url === '/api/public/stats' && req.params.get('days') === '7'
    );
    request.flush(payload({ days: '7' }));
    await expect(pending).resolves.toMatchObject({ days: '7' });
    http.verify();
  });

  it('surfaces transport errors to the page', async () => {
    const { service, http } = serviceAndHttp();
    const pending = service.getStats();
    http.expectOne((req) => req.url === '/api/public/stats').error(new ProgressEvent('error'));
    await expect(pending).rejects.toBeTruthy();
    http.verify();
  });
});
