export interface Team {
  id: number;
  name: string;
  owners: { id: number; username: string }[];
  member_count: number;
  model_count: number;
  default_cloud_rpm_limit: number | null;
  default_cloud_tpm_limit: number | null;
  default_local_rpm_limit: number | null;
  default_local_tpm_limit: number | null;
  is_caller_owner: boolean;
}

export interface AdminUser {
  id: number;
  username: string;
}

export interface TeamDetail {
  id: number;
  name: string;
  is_caller_owner: boolean;
  team_monthly_budget_micro_cents: number | null;
  budget_used_micro_cents: number | null;
  default_monthly_budget_micro_cents: number | null;
  default_cloud_rpm_limit: number | null;
  default_cloud_tpm_limit: number | null;
  default_local_rpm_limit: number | null;
  default_local_tpm_limit: number | null;
}

export interface TeamMember {
  id: number;
  username: string;
  prename: string;
  name: string;
  email: string;
  is_owner: boolean;
  developer_monthly_budget_micro_cents: number | null;
}

export interface TeamApiKey {
  id: number;
  name: string;
  user_id?: number;
  key_value?: string;
  key_type?: string;
  environment?: string;
  default_priority?: number;
  log?: 'BILLING' | 'FULL';
  use_custom_permissions?: boolean;
  used_micro_cents?: number;
  settings?: {
    budget_limit_micro_cents?: number | null;
    cloud_rpm_limit?: number | null;
    cloud_tpm_limit?: number | null;
    local_rpm_limit?: number | null;
    local_tpm_limit?: number | null;
  };
  monthly_budget_micro_cents: number | null;
  cloud_rpm_limit: number | null;
  cloud_tpm_limit: number | null;
  local_rpm_limit: number | null;
  local_tpm_limit: number | null;
}

export interface ApiKeyUpdatePayload {
  environment?: string;
  default_priority?: number;
  log?: 'BILLING' | 'FULL';
  use_custom_permissions?: boolean;
  budget_limit_micro_cents?: number | null;
  cloud_rpm_limit?: number | null;
  cloud_tpm_limit?: number | null;
  local_rpm_limit?: number | null;
  local_tpm_limit?: number | null;
}

export interface CreateApiKeyPayload {
  name: string;
  key_type: 'application';
  environment: string;
  default_priority: number;
  log: 'BILLING';
  settings: {
    budget_limit_micro_cents: number | null;
    cloud_rpm_limit: number | null;
    cloud_tpm_limit: number | null;
    local_rpm_limit: number | null;
    local_tpm_limit: number | null;
  };
}

export interface ProviderItem {
  id: number;
  name: string;
  base_url?: string;
}

export interface ProviderModelItem {
  model_id: number;
  model_name: string;
}

export interface TeamModelPermission {
  id: number;
  model_id: number;
  model_name: string;
  provider_name: string;
}

export interface TeamLimitsPayload {
  team_monthly_budget_micro_cents?: number | null;
  default_monthly_budget_micro_cents?: number | null;
  default_cloud_rpm_limit?: number | null;
  default_cloud_tpm_limit?: number | null;
  default_local_rpm_limit?: number | null;
  default_local_tpm_limit?: number | null;
}

export interface MyTeam {
  id: number;
  name: string;
  is_caller_owner: boolean;
  team_monthly_budget_micro_cents: number | null;
  budget_used_micro_cents: number;
  member_count: number;
  owners: { id: number; prename: string; name: string }[];
}
