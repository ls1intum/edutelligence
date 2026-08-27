import { RequestItem } from '../../../statistics/statistics.models';

/**
 * What one team is doing and has spent (issue #776).
 *
 * Lives in the team's own detail view rather than a page of its own: it is one
 * more thing you look at about a team, next to its members, keys and cloud
 * spend, and pulling it out into a separate destination made it something you
 * had to remember existed.
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

/** One entry of the requester filter, with how much picking it would select. */
export interface TeamRequester {
  id: number;
  label: string;
  requestCount: number;
}

/** Where to continue the request list from. */
export interface RequestCursor {
  ts: string;
  request_id: string;
}

export interface TeamActivityPayload {
  team_id: number;
  days: number;
  since: string;
  live: TeamLiveCounts;
  keys: TeamKeyUsage[];
  total_tokens: number;
  total_requests: number;
  requesters: TeamRequester[];
  requests: RequestItem[];
  requests_total: number;
  requests_has_more: boolean;
  requests_next_cursor: RequestCursor | null;
}
