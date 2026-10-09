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
  /** Settled successes on published teams (includes application/service keys). */
  successful_requests: number;
  /**
   * Active-student successes divided by {@link students}. Application and
   * service-key traffic is excluded so the average matches the student cohort.
   */
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
  /** Tokens of the successful requests above. */
  tokens: number;
  local_cloud_tokens: {
    local: number;
    cloud: number;
    unknown?: number;
  };
  /** Distinct people (students and staff) with a successful request. */
  active_persons: number;
  /** Published teams with a successful request. */
  active_teams: number;
  usage_per_person: PublicUsageDistribution;
  usage_per_team: PublicUsageDistribution;
  categories: PublicCategoryStats[];
  models: {
    all: PublicModelStats[];
    local: PublicModelStats[];
    cloud: PublicModelStats[];
  };
  /** Independent of the window: the last complete weeks. */
  regular_activity: PublicRegularActivity;
  /** Independent of the window: every month since the first request. */
  monthly: PublicMonthStats[];
  agent: PublicAgentStats;
}

/** Median and 90th percentile of one figure across active people or teams. */
export interface PublicPercentiles {
  median: number;
  p90: number;
}

/**
 * Requests, tokens and active days per active person (or team) in the window.
 * The figures are null while too few are active to publish them.
 */
export interface PublicUsageDistribution {
  count: number;
  suppressed: boolean;
  requests: PublicPercentiles | null;
  tokens: PublicPercentiles | null;
  active_days: PublicPercentiles | null;
}

/** One team category (free text set in team settings; null = uncategorized). */
export interface PublicCategoryStats {
  category: string | null;
  teams: number;
  requests: number;
  tokens: number;
}

/** One model's successful requests and tokens; `other` sums the long tail. */
export interface PublicModelStats {
  model: string | null;
  requests: number;
  tokens: number;
  other: boolean;
}

/** People and teams active in most of the last complete weeks. */
export interface PublicRegularActivity {
  weeks: number;
  min_weeks: number;
  from: string;
  to: string;
  persons_any: number;
  persons_regular: number;
  persons_every_week: number;
  teams_any: number;
  teams_regular: number;
  teams_every_week: number;
}

/** One calendar month (UTC) of the all-time series. */
export interface PublicMonthStats {
  /** `YYYY-MM` */
  month: string;
  teams: number;
  persons: number;
  students: number;
  requests: number;
  local_requests: number;
  tokens: number;
  agent_sessions: number;
  agent_users: number;
}

/** Logos Agent sessions in the window. */
export interface PublicAgentStats {
  sessions: number;
  users: number;
  succeeded: number;
  pull_requests: number;
  /** `YYYY-MM-DD` of the first session ever; null before the first one. */
  first_session_day: string | null;
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
