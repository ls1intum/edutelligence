export type AgentSessionStatus =
  | 'queued'
  | 'starting'
  | 'running'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export type AgentEventKind =
  | 'log'
  | 'status'
  | 'pull_request'
  | 'deploy'
  | 'screenshot'
  | 'capacity'
  | 'error';

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
  cost_eur: number;
  screenshot_count: number;
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
];

export function isActive(status: AgentSessionStatus): boolean {
  return ACTIVE_SESSION_STATUSES.includes(status);
}
