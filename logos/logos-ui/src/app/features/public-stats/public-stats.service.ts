import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** One team's share of the platform's successful requests. */
export interface PublicTeamStats {
  team_id: number | null;
  team_name: string | null;
  requests: number;
}

/** Allowed rolling windows for GET /api/public/stats?days=… */
export type PublicStatsDays = '7' | '30' | '90' | '365' | 'all';

export const PUBLIC_STATS_DAY_OPTIONS: { value: PublicStatsDays; label: string }[] = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '365 days' },
  { value: 'all', label: 'All time' },
];

export const DEFAULT_PUBLIC_STATS_DAYS: PublicStatsDays = '30';

/**
 * The aggregate picture of opted-in teams, as GET /api/public/stats reports
 * it. Every request figure counts settled successes inside the selected window.
 */
export interface PublicStats {
  /** Echo of the requested window (default 30). */
  days: PublicStatsDays;
  /** Distinct active users with a successful request in the window. */
  students: number;
  /** Teams an admin opted into the public page. */
  teams: number;
  successful_requests: number;
  average_requests_per_user: number;
  requests_per_team: PublicTeamStats[];
  /** Successful requests by API key type (unknown = deleted key). */
  requests_by_key_type: {
    developer: number;
    application: number;
    service: number;
    unknown?: number;
  };
  /** Successful requests by serving lane (unknown = deleted provider). */
  local_cloud_requests: {
    local: number;
    cloud: number;
    unknown?: number;
  };
}

/**
 * Data access for the public stats page. The endpoint takes no credential —
 * the auth interceptor must not attach a bearer to it.
 */
@Injectable({ providedIn: 'root' })
export class PublicStatsService {
  private http = inject(HttpClient);

  getStats(days: PublicStatsDays = DEFAULT_PUBLIC_STATS_DAYS): Promise<PublicStats> {
    const params = new HttpParams().set('days', days);
    return firstValueFrom(this.http.get<PublicStats>('/api/public/stats', { params }));
  }
}
