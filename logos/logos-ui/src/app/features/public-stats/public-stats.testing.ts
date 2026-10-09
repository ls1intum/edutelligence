import { PublicStats } from './public-stats.service';

type UsageFields = Omit<
  PublicStats,
  | 'days'
  | 'students'
  | 'teams'
  | 'successful_requests'
  | 'average_requests_per_user'
  | 'requests_per_team'
  | 'requests_by_key_type'
  | 'local_cloud_requests'
>;

/** The usage part of a public stats response, empty unless overridden. */
export function usageFields(overrides: Partial<UsageFields> = {}): UsageFields {
  const empty = { count: 0, suppressed: true, requests: null, tokens: null, active_days: null };
  return {
    tokens: 0,
    local_cloud_tokens: { local: 0, cloud: 0 },
    active_persons: 0,
    active_teams: 0,
    usage_per_person: empty,
    usage_per_team: empty,
    categories: [],
    models: { all: [], local: [], cloud: [] },
    regular_activity: {
      weeks: 4,
      min_weeks: 3,
      from: '2026-09-07',
      to: '2026-10-04',
      persons_any: 0,
      persons_regular: 0,
      persons_every_week: 0,
      teams_any: 0,
      teams_regular: 0,
      teams_every_week: 0,
    },
    monthly: [],
    agent: { sessions: 0, users: 0, succeeded: 0, pull_requests: 0, first_session_day: null },
    ...overrides,
  };
}
