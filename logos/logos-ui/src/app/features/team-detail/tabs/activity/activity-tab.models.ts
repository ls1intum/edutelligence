import { RequestItem } from '../../../statistics/statistics.models';

/**
 * What one team is doing and has spent.
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

/** One distinct question asked of this team, and how many times. */
export interface TeamMostAskedQuestion {
  question: string;
  count: number;
}

/**
 * Where an export slice ends, and the next, older one continues from.
 *
 * Opaque on purpose: the token is the server's own encoding of the window
 * the walk started in and the row behind the slice. The view never parses
 * it — it hands it back, and a token it cannot show as a valid continuation
 * is simply not shown.
 */
export type ExportCursor = string;

export interface TeamActivityPayload {
  team_id: number;
  days: number;
  since: string;
  /**
   * Whether any key of the team is opted into FULL logging — the only switch
   * under which request and response content is stored at all, so the view
   * can hint at an empty export before the download is started.
   */
  full_logging_enabled: boolean;
  live: TeamLiveCounts;
  keys: TeamKeyUsage[];
  total_tokens: number;
  total_requests: number;
  requesters: TeamRequester[];
  most_asked_questions: TeamMostAskedQuestion[];
  /**
   * How many of the team's newest full-logging requests the ranking is cut
   * from — the section is a sample of the window, and the number says how
   * large.
   */
  most_asked_sample_limit?: number;
  requests: RequestItem[];
  requests_total: number;
  requests_has_more: boolean;
  requests_next_cursor: RequestCursor | null;
}

