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
  team: MyKeyTeam;
}

export interface ModelAccess {
  model_name: string;
  provider_name?: string;
  provider_type: string;
  /**
   * Smallest context window (tokens) any worker currently serves for the model;
   * null when none reports one. A request may land on any worker, so this is the
   * only figure that holds without the orchestrator routing around it.
   */
  context_window: number | null;
  /** Largest window currently served anywhere. Absent when unknown. */
  context_window_best?: number | null;
  /**
   * The model's own context length — what a lane serves once it gets all the KV
   * cache it asks for. Known even while nothing is loaded, which makes it the
   * number to use when a config file has to commit to one up front.
   */
  context_window_native?: number | null;
}
