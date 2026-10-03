import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** One team's share of the platform's successful requests. */
export interface PublicTeamStats {
  team_id: number | null;
  team_name: string | null;
  requests: number;
}

/**
 * The aggregate picture of the platform, as GET /api/public/stats reports
 * it. Every request figure counts settled successes only.
 */
export interface PublicStats {
  /** Registered students still active. */
  students: number;
  teams: number;
  successful_requests: number;
  average_requests_per_user: number;
  requests_per_team: PublicTeamStats[];
  /** Successful requests by API key type. */
  requests_by_key_type: {
    developer: number;
    application: number;
    service: number;
  };
  /** Successful requests by serving lane. */
  local_cloud_requests: {
    local: number;
    cloud: number;
  };
}

/**
 * Data access for the public stats page. The endpoint takes no credential —
 * the auth interceptor must not attach a bearer to it.
 */
@Injectable({ providedIn: 'root' })
export class PublicStatsService {
  private http = inject(HttpClient);

  getStats(): Promise<PublicStats> {
    return firstValueFrom(this.http.get<PublicStats>('/api/public/stats'));
  }
}
