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
  /** True when the team is linked to a Keycloak group; name and existence are Keycloak-owned. */
  managed: boolean;
  /** The linked Keycloak group (or realm role); null when the team is Logos-owned. */
  keycloak_group: string | null;
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
  /** True when the team is linked to a Keycloak group; name and existence are Keycloak-owned. */
  managed: boolean;
  /** The linked Keycloak group (or realm role); null when the team is Logos-owned. */
  keycloak_group: string | null;
  /** When true, this team's name and traffic appear on the public stats page. */
  show_on_public_stats: boolean;
  /** Free-text group the public stats page sorts this team into; null = uncategorized. */
  public_category: string | null;
}

/** A Keycloak claim name a team can be linked to, as offered by the group picker. */
export interface KeycloakGroupOption {
  name: string;
  source: 'group' | 'role';
  linked_team_id: number | null;
  linked_team_name: string | null;
}

export interface KeycloakGroupDirectory {
  /** False when the deployment has no Keycloak directory access — type the group instead. */
  available: boolean;
  groups: KeycloakGroupOption[];
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
  show_on_public_stats?: boolean;
  /** Blank clears the category. */
  public_category?: string;
}

/** Per-provider monthly budget override (null = unlimited / sponsored). */
export interface TeamProviderBudget {
  provider_id: number;
  provider_name: string;
  provider_type?: string;
  monthly_budget_micro_cents: number | null;
}

/** GitHub repository linked to a team for later AI-workflow / SLO analysis. */
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
  /** The owner saved diagram_mermaid; re-analyses keep it. */
  diagram_set_by_owner?: boolean;
  /** Agent Mermaid that differs from the owner's; Accept / Keep mine. */
  proposed_diagram_mermaid?: string | null;
}

export type RecommendedSlo = 'ux-critical' | 'ux-high-prio' | 'ux-background';

export type RecommendationReviewStatus = 'pending' | 'accepted' | 'overridden' | 'rejected';

/** Ordered optimization goals for a call site (most important first). */
export type ObjectiveKey = 'latency' | 'quality' | 'price';

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
  recommended_slo: RecommendedSlo;
  /** Ranking of latency / quality / price (most important first). */
  objective_priority?: ObjectiveKey[];
  confidence: number;
  justification: string;
  traffic_flags?: Record<string, unknown> | null;
  review_status: RecommendationReviewStatus;
  confirmed_slo?: RecommendedSlo | null;
  confirmed_objective_priority?: ObjectiveKey[] | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
  /** The owner picked detected_model; re-analyses keep it. */
  model_set_by_owner?: boolean;
  /** The review was carried over from an earlier decision by a re-analysis. */
  review_carried_over?: boolean;
  /** The owner's decision on the recommendation this one succeeds, when there was one. */
  previous?: PreviousDecision | null;
}

/** What was decided on a call site before the latest analysis proposed it again. */
export interface PreviousDecision {
  id: number;
  review_status: Exclude<RecommendationReviewStatus, 'pending'>;
  slo: RecommendedSlo;
  objective_priority: ObjectiveKey[];
  reviewed_at?: string | null;
}

/** Result of queueing an analysis of every linked repository. */
export interface AnalyzeAllResult {
  queued: number;
  already_in_flight: number;
  message: string;
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
  confirmed_slo?: RecommendedSlo;
  confirmed_objective_priority?: ObjectiveKey[];
  api_key_id?: number;
  /** "No key": bind and re-prioritise no key, not even the one linked before. */
  no_api_key?: boolean;
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
