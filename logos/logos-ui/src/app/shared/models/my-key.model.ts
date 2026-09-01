export interface MyKeySettings {
  budget_limit_micro_cents: number | null;
  cloud_rpm_limit: number | null;
  cloud_tpm_limit: number | null;
  local_rpm_limit: number | null;
  local_tpm_limit: number | null;
}

export interface MyKeyTeam {
  id: number;
  name: string;
  team_monthly_budget_micro_cents: number | null;
  budget_used_micro_cents: number;
}

/**
 * Requests and tokens this key sent inside one rate-limit window, split the
 * way the limits are enforced (cloud vs. local). The figures are what the
 * sliding window is currently counting, so they can be held directly against
 * the rpm/tpm limits in {@link MyKeySettings}.
 */
export interface RateLimitUsage {
  window_seconds: number;
  cloud_requests: number;
  cloud_tokens: number;
  local_requests: number;
  local_tokens: number;
}

export interface MyKey {
  id: number;
  name: string;
  key_value: string;
  key_type: string;
  environment: string;
  log: 'BILLING' | 'FULL';
  use_custom_permissions: boolean;
  used_micro_cents: number;
  settings: MyKeySettings | null;
  last_used_at: string | null;
  rate_limit_usage: RateLimitUsage | null;
  team: MyKeyTeam;
}

export interface ModelAccess {
  model_name: string;
  provider_name?: string;
  provider_type: string;
  /**
   * Smallest context window (tokens) being served right now; null when nothing
   * is known. A request may land on any deployment, so this is the only figure
   * that holds without the orchestrator routing around it.
   */
  context_window_current_min: number | null;
  /** Largest window being served right now. Absent when unknown. */
  context_window_current_max?: number | null;
  /**
   * The widest this model is ever served with — independent of what is loaded
   * at the moment, which makes it the number to use when a config file has to
   * commit to one up front.
   */
  context_window_overall?: number | null;
}
