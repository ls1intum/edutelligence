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
  settings: MyKeySettings;
  last_used_at: string | null;
  team: MyKeyTeam;
}

export interface ModelAccess {
  model_name: string;
  provider_name: string;
  provider_type: string;
}
