export type AgentSessionStatus =
  | 'queued'
  | 'starting'
  | 'running'
  | 'paused'
  | 'finalizing'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export type AgentEventKind =
  'log' | 'status' | 'pull_request' | 'deploy' | 'screenshot' | 'capacity' | 'error';

export interface AgentWorkspace {
  id: number;
  name: string;
  base_branch: string;
  volume_name: string;
  created_by: string;
  created_at: string;
  active_sessions: number;
}

export interface AgentSession {
  id: number;
  workspace_id: number;
  workspace_name: string;
  task: string;
  status: AgentSessionStatus;
  model: string | null;
  branch_name: string | null;
  pr_url: string | null;
  created_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  error: string | null;
  tokens_in: number;
  tokens_out: number;
  /** What the agent reported spending, in US dollars. */
  cost_usd: number;
  screenshot_count: number;
  /** Set when the runner queued this session itself: 'issue' or 'review'. */
  trigger_kind: string | null;
  /** Which event it reacted to, e.g. 'issue-812'. */
  trigger_ref: string | null;
  /** How urgent the work is (higher runs first), and why. */
  priority: number;
  priority_reason: string | null;
  /**
   * The environment notes this session was handed, as they stood when it
   * started. Null for a session that never started and for ones that ran
   * before the runner kept a copy.
   */
  environment_notes: string | null;
}

/** The standing text every session is given, and whether it is the default. */
export interface AgentInstructions {
  house_rules: string;
  environment_notes: string;
  house_rules_default: boolean;
  environment_notes_default: boolean;
  updated_by: string;
}

export interface AgentEvent {
  id: number;
  session_id: number;
  ts: string;
  kind: AgentEventKind;
  payload: Record<string, unknown>;
}

/** What the runner currently believes about spare serving capacity. */
export interface AgentCapacity {
  load: number;
  total_slots: number;
  busy_slots: number;
  sessions_running: number;
  sessions_queued: number;
  sessions_paused: number;
  max_parallel: number;
  may_start: boolean;
  reason: string;
  /** False when the agent key could reach a cloud model: nothing starts. */
  models_local_only: boolean;
  models_detail: string;
}

/** What an operator has changed about the runner while it runs. */
export type AgentRunnerMode = 'running' | 'draining' | 'paused';

export interface AgentControls {
  /** running: as configured · draining: nothing new · paused: hand it all back. */
  mode: AgentRunnerMode;
  mode_reason: string;
  paused: boolean;
  admits_new_sessions: boolean;
  /** The ceiling in force right now. */
  max_parallel: number;
  /** Null when the deployment's configured ceiling applies. */
  max_parallel_override: number | null;
  max_parallel_configured: number;
  updated_by: string;
}

/** The locally served models a session may be driven by. */
export interface AgentModels {
  models: string[];
  default: string;
  local_only: boolean;
  detail: string;
}

/** Whether the runner reacts to the repository, and what it has queued. */
export interface AgentTriggers {
  enabled: boolean;
  polling: boolean;
  /** The GitHub account whose assignments and mentions it answers. */
  account: string;
  poll_interval_s: number;
  max_active_sessions: number;
  active_sessions: number;
  last_pass: string | null;
  queued_total: number;
  last_error: string;
}

export interface CreateSessionRequest {
  workspace_id: number;
  task: string;
  model?: string | null;
  open_pull_request: boolean;
  deploy_to_dev: boolean;
  screenshot_paths: string[];
}

/** Sessions in these states still hold a container and a workspace. */
export const ACTIVE_SESSION_STATUSES: readonly AgentSessionStatus[] = [
  'queued',
  'starting',
  'running',
  'paused',
  'finalizing',
];

export function isActive(status: AgentSessionStatus): boolean {
  return ACTIVE_SESSION_STATUSES.includes(status);
}
