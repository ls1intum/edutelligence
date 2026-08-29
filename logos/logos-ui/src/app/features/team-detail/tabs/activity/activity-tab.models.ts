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
  /**
   * Whether any key of the team is opted into FULL logging — the only switch
   * under which request and response content is stored at all, so the view
   * can hint at an empty export before the download is started (issue #667).
   */
  full_logging_enabled: boolean;
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

// ── Trace export (issue #667) ────────────────────────────────────────────────

/**
 * One request trace of the team export. Every row carries the lifecycle
 * metadata; only the rows the orchestrator recorded at FULL privacy (the ones
 * the requester consented to) also carry the request and response content —
 * for the billing-only rows the payload fields are absent.
 *
 * The payload fields are `unknown` on purpose — their shape is whatever the
 * caller sent to the model, and the export must not pretend to know it.
 */
export interface TraceExportItem {
  request_id: string | null;
  timestamp_request: string | null;
  timestamp_forwarding: string | null;
  timestamp_response: string | null;
  time_at_first_token: string | null;
  privacy_level: string;
  model_name: string | null;
  provider_type: string | null;
  environment: string | null;
  api_key_id: number | null;
  api_key_name: string | null;
  username: string | null;
  full_name: string | null;
  team_name: string | null;
  client_ip: string | null;
  status: string;
  error_message: string | null;
  priority: string | null;
  initial_priority: string | null;
  priority_when_scheduled: string | null;
  queue_depth_at_enqueue: number | null;
  queue_depth_at_schedule: number | null;
  queue_depth_at_arrival: number | null;
  timeout_s: number | null;
  utilization_at_arrival: number | null;
  queue_wait_ms: number | null;
  was_cold_start: boolean | null;
  load_duration_ms: number | null;
  available_vram_mb: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_microcents: number | null;
  classification_statistics: unknown;
  input_payload: unknown;
  headers: unknown;
  response_payload: unknown;
}

/** Envelope of the trace export — the downloaded file is this object. */
export interface TraceExport {
  team_id: number;
  team_name: string | null;
  days: number;
  since: string;
  count: number;
  /** Whether any key of the team has full (consent) logging activated. */
  full_logging_enabled: boolean;
  /**
   * Present only when not a single row of the export carries content — the
   * file explaining itself why the payload columns are all empty.
   */
  note?: string;
  /** True when the window held more traces than one export may carry. */
  truncated: boolean;
  traces: TraceExportItem[];
}
