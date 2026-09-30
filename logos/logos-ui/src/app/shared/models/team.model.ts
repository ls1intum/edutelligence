export interface Team {
  id: number;
  name: string;
  owners: { id: number; username: string; prename: string; name: string }[];
  member_count: number;
  model_count: number;
  default_cloud_rpm_limit: number | null;
  default_cloud_tpm_limit: number | null;
  default_local_rpm_limit: number | null;
  default_local_tpm_limit: number | null;
  /** Queue priority of the team's traffic (1..10, same scale as API-key priorities); null = not set. */
  priority: number | null;
  is_caller_owner: boolean;
  /** True when the team is provisioned from a Keycloak group; name and existence are Keycloak-owned. */
  managed: boolean;
}

export interface AdminUser {
  id: number;
  username: string;
  prename: string;
  name: string;
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
  /** Queue priority of the team's traffic (1..10); null = not set. */
  priority: number | null;
  /** True when the team is provisioned from a Keycloak group; name and existence are Keycloak-owned. */
  managed: boolean;
}

export interface TeamMember {
  id: number;
  username: string;
  prename: string;
  name: string;
  email: string;
  is_owner: boolean;
  developer_monthly_budget_micro_cents: number | null;
  /** True when the membership comes from a Keycloak group; it is re-added on sync and cannot be removed here. */
  managed: boolean;
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
  provider_type?: 'logosnode' | 'cloud';
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

/** GitHub repository linked to a team for later AI-workflow / SLA analysis. */
export interface TeamRepository {
  id: number;
  team_id: number;
  repo_url: string;
  repo_slug: string;
  branch: string;
  paths: string[] | null;
  created_at?: string;
  updated_at?: string;
  /** True when a non-revoked deploy key (or similar) is stored for this link. */
  has_credentials?: boolean;
  /** Latest succeeded analysis summary, if any. */
  latest_analysis?: WorkflowAnalysisSummary | null;
}

export interface TeamRepositoryPayload {
  repo_url: string;
  branch?: string;
  paths?: string[] | null;
}

export interface WorkflowAnalysisSummary {
  id: number;
  status: string;
  source?: string;
  commit_sha?: string | null;
  finished_at?: string | null;
}

export interface AiWorkflow {
  id: number;
  analysis_id: number;
  name: string;
  trigger_summary?: string | null;
  diagram_mermaid: string;
  sort_order: number;
}

export type RecommendedSla = 'ux-critical' | 'ux-high-prio' | 'ux-background';

export type RecommendationReviewStatus = 'pending' | 'accepted' | 'overridden' | 'rejected';

export interface AiLlmCallRecommendation {
  id: number;
  analysis_id: number;
  workflow_id?: number | null;
  team_id: number;
  file_path: string;
  start_line?: number | null;
  end_line?: number | null;
  code_url?: string | null;
  detected_model?: string | null;
  api_key_id?: number | null;
  recommended_sla: RecommendedSla;
  confidence: number;
  justification: string;
  traffic_flags?: Record<string, unknown> | null;
  review_status: RecommendationReviewStatus;
  confirmed_sla?: RecommendedSla | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
}

export interface TeamWorkflowsResponse {
  team_id: number;
  repositories: {
    id: number;
    repo_slug: string;
    repo_url: string;
    branch: string;
    latest_analysis: WorkflowAnalysisSummary | null;
    workflows: AiWorkflow[];
    recommendations: AiLlmCallRecommendation[];
  }[];
  pending_recommendations: AiLlmCallRecommendation[];
}

export interface ReviewRecommendationPayload {
  action: 'accept' | 'override' | 'reject';
  confirmed_sla?: RecommendedSla;
  api_key_id?: number;
}

export interface StoreDeployKeyPayload {
  private_key_pem: string;
  public_key_fingerprint?: string;
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
