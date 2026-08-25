/**
 * The team activity view's payload (issue #776).
 *
 * App administrators asked for what the statistics page gives Logos admins,
 * narrowed to their own teams and cut down to two questions: what is running
 * right now, and what has the team spent.
 */

/** Requests by stage. Counts, not a sample. */
export interface TeamLiveCounts {
  /** Accepted, not yet handed to a provider. */
  queued: number;
  /** Forwarded, no response recorded yet. */
  running: number;
  /** Completed inside the selected window. */
  finished: number;
  /** Of those, how many ended in an error. */
  failed: number;
}

/** What one API key spent over the window. */
export interface TeamKeyUsage {
  key_id: number;
  key_name: string;
  key_type: string;
  environment: string | null;
  request_count: number;
  total_tokens: number;
}

export interface TeamActivityPayload {
  team_id: number;
  days: number;
  since: string;
  live: TeamLiveCounts;
  keys: TeamKeyUsage[];
  total_tokens: number;
  total_requests: number;
}
