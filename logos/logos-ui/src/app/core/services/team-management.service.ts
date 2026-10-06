import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
  AnalyzeAllResult,
  Team, AdminUser, TeamDetail, TeamMember, TeamApiKey,
  ProviderItem, ProviderModelItem, TeamModelPermission, TeamLimitsPayload,
  TeamProviderBudget,
  ApiKeyUpdatePayload, CreateApiKeyPayload, MyTeam, TeamRepository,
  TeamRepositoryPayload, TeamWorkflowsResponse, ReviewRecommendationPayload,
  StoreDeployKeyPayload, AiLlmCallRecommendation,
} from '../../shared/models/team.model';

export interface TeamMembersResponse {
  team: TeamDetail;
  members: TeamMember[];
}

@Injectable({ providedIn: 'root' })
export class TeamManagementService {
  private http = inject(HttpClient);

  // ── List page ──────────────────────────────────────────────────────────────
  getTeams(): Promise<Team[]> {
    return firstValueFrom(this.http.get<Team[]>('/api/teams'));
  }

  createTeam(name: string, ownerIds: number[]): Promise<Team> {
    return firstValueFrom(this.http.post<Team>('/api/teams', { name, owner_ids: ownerIds }));
  }

  deleteTeam(id: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`/api/teams/${id}`));
  }

  getAdminUsers(): Promise<AdminUser[]> {
    return firstValueFrom(this.http.get<AdminUser[]>('/api/users/admins'));
  }

  // ── Detail page ────────────────────────────────────────────────────────────
  getTeamWithMembers(teamId: number): Promise<TeamMembersResponse> {
    return firstValueFrom(this.http.get<TeamMembersResponse>(`/api/teams/${teamId}/members`));
  }

  renameTeam(teamId: number, name: string): Promise<{ name: string }> {
    return firstValueFrom(this.http.patch<{ name: string }>(`/api/teams/${teamId}/name`, { name }));
  }

  updateTeamLimits(teamId: number, payload: TeamLimitsPayload): Promise<void> {
    return firstValueFrom(this.http.patch<void>(`/api/teams/${teamId}`, payload));
  }

  getTeamProviderBudgets(teamId: number): Promise<TeamProviderBudget[]> {
    return firstValueFrom(
      this.http.get<TeamProviderBudget[]>(`/api/admin/teams/${teamId}/provider-budgets`),
    );
  }

  upsertTeamProviderBudget(
    teamId: number,
    providerId: number,
    monthlyBudgetMicroCents: number | null,
  ): Promise<TeamProviderBudget> {
    return firstValueFrom(
      this.http.put<TeamProviderBudget>(
        `/api/admin/teams/${teamId}/provider-budgets/${providerId}`,
        { monthly_budget_micro_cents: monthlyBudgetMicroCents },
      ),
    );
  }

  deleteTeamProviderBudget(teamId: number, providerId: number): Promise<void> {
    return firstValueFrom(
      this.http.delete<void>(`/api/admin/teams/${teamId}/provider-budgets/${providerId}`),
    );
  }

  /** Sets the queue priority of a team's traffic (logos_admin only); null unsets it. */
  updateTeamPriority(teamId: number, priority: number | null): Promise<void> {
    return firstValueFrom(this.http.patch<void>(`/api/teams/${teamId}/priority`, { priority }));
  }

  getTeamApiKeys(teamId: number): Promise<TeamApiKey[]> {
    return firstValueFrom(this.http.get<TeamApiKey[]>(`/api/admin/teams/${teamId}/api-keys`));
  }

  getTeamRepositories(teamId: number): Promise<TeamRepository[]> {
    return firstValueFrom(this.http.get<TeamRepository[]>(`/api/admin/teams/${teamId}/repositories`));
  }

  createTeamRepository(teamId: number, payload: TeamRepositoryPayload): Promise<TeamRepository> {
    return firstValueFrom(
      this.http.post<TeamRepository>(`/api/admin/teams/${teamId}/repositories`, payload),
    );
  }

  updateTeamRepository(
    teamId: number,
    linkId: number,
    payload: Partial<TeamRepositoryPayload>,
  ): Promise<TeamRepository> {
    return firstValueFrom(
      this.http.patch<TeamRepository>(`/api/admin/teams/${teamId}/repositories/${linkId}`, payload),
    );
  }

  deleteTeamRepository(teamId: number, linkId: number): Promise<void> {
    return firstValueFrom(
      this.http.delete<void>(`/api/admin/teams/${teamId}/repositories/${linkId}`),
    );
  }

  getTeamWorkflows(teamId: number): Promise<TeamWorkflowsResponse> {
    return firstValueFrom(
      this.http.get<TeamWorkflowsResponse>(`/api/admin/teams/${teamId}/workflows`),
    );
  }

  analyzeRepositoryAgent(teamId: number, linkId: number): Promise<unknown> {
    return firstValueFrom(
      this.http.post(`/api/admin/teams/${teamId}/repositories/${linkId}/analyze/agent`, {}),
    );
  }

  /** Queue an agent analysis of every linked repository (Logos Admins). */
  analyzeAllRepositories(): Promise<AnalyzeAllResult> {
    return firstValueFrom(this.http.post<AnalyzeAllResult>('/api/admin/repositories/analyze', {}));
  }

  /** Record which model a recommended call site uses; null clears it. */
  setRecommendationModel(
    teamId: number,
    recId: number,
    model: string | null,
  ): Promise<AiLlmCallRecommendation> {
    return firstValueFrom(
      this.http.put<AiLlmCallRecommendation>(
        `/api/admin/teams/${teamId}/recommendations/${recId}/model`,
        { model },
      ),
    );
  }

  reviewRecommendation(
    teamId: number,
    recId: number,
    payload: ReviewRecommendationPayload,
  ): Promise<AiLlmCallRecommendation> {
    return firstValueFrom(
      this.http.post<AiLlmCallRecommendation>(
        `/api/admin/teams/${teamId}/recommendations/${recId}/review`,
        payload,
      ),
    );
  }

  storeRepositoryCredentials(
    teamId: number,
    linkId: number,
    payload: StoreDeployKeyPayload,
  ): Promise<{ has_credentials: boolean; public_key_fingerprint?: string }> {
    return firstValueFrom(
      this.http.put<{ has_credentials: boolean; public_key_fingerprint?: string }>(
        `/api/admin/teams/${teamId}/repositories/${linkId}/credentials`,
        payload,
      ),
    );
  }

  revokeRepositoryCredentials(teamId: number, linkId: number): Promise<void> {
    return firstValueFrom(
      this.http.delete<void>(`/api/admin/teams/${teamId}/repositories/${linkId}/credentials`),
    );
  }

  getTeamModelPermissions(teamId: number): Promise<number[]> {
    return firstValueFrom(this.http.get<number[]>(`/api/admin/teams/${teamId}/model-permissions`));
  }

  setTeamModelPermissions(teamId: number, modelIds: number[]): Promise<void> {
    return firstValueFrom(this.http.put<void>(`/api/admin/teams/${teamId}/model-permissions`, { model_ids: modelIds }));
  }

  getTeamProviderPermissions(teamId: number): Promise<number[]> {
    return firstValueFrom(this.http.get<number[]>(`/api/admin/teams/${teamId}/provider-permissions`));
  }

  setTeamProviderPermissions(teamId: number, providerIds: number[]): Promise<void> {
    return firstValueFrom(this.http.put<void>(`/api/admin/teams/${teamId}/provider-permissions`, { provider_ids: providerIds }));
  }

  /** Atomic single-grant add (model access page) — no full-set replacement. */
  addTeamProviderPermission(teamId: number, providerId: number): Promise<void> {
    return firstValueFrom(this.http.post<void>(`/api/admin/teams/${teamId}/provider-permissions/${providerId}`, {}));
  }

  /** Atomic single-grant removal (model access page) — no full-set replacement. */
  removeTeamProviderPermission(teamId: number, providerId: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`/api/admin/teams/${teamId}/provider-permissions/${providerId}`));
  }

  getAllProviders(): Promise<ProviderItem[]> {
    return firstValueFrom(this.http.post<ProviderItem[]>('/api/logosdb/get_providers', {}));
  }

  getProviderModels(providerId: number): Promise<ProviderModelItem[]> {
    return firstValueFrom(this.http.post<ProviderModelItem[]>('/api/logosdb/get_provider_models', { provider_id: providerId }));
  }

  getAllUsers(): Promise<AdminUser[]> {
    return firstValueFrom(this.http.get<AdminUser[]>('/api/users'));
  }

  addTeamMember(teamId: number, userId: number, role: 'owner' | 'member'): Promise<void> {
    const body: Record<string, unknown> = { user_id: userId };
    if (role === 'owner') body['is_owner'] = true;
    return firstValueFrom(this.http.post<void>(`/api/teams/${teamId}/members`, body));
  }

  removeTeamMember(teamId: number, userId: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`/api/teams/${teamId}/members/${userId}`));
  }

  updateTeamMemberOwner(teamId: number, userId: number, isOwner: boolean): Promise<void> {
    return firstValueFrom(
      this.http.patch<void>(`/api/teams/${teamId}/members/${userId}`, { is_owner: isOwner }),
    );
  }

  // ── API key editing ────────────────────────────────────────────────────────
  updateApiKey(keyId: number, payload: ApiKeyUpdatePayload): Promise<void> {
    return firstValueFrom(this.http.patch<void>(`/api/admin/api-keys/${keyId}`, payload));
  }

  getApiKeyModelPermissions(keyId: number): Promise<number[]> {
    return firstValueFrom(this.http.get<number[]>(`/api/admin/api-keys/${keyId}/model-permissions`));
  }

  getApiKeyProviderPermissions(keyId: number): Promise<number[]> {
    return firstValueFrom(this.http.get<number[]>(`/api/admin/api-keys/${keyId}/provider-permissions`));
  }

  setApiKeyModelPermissions(keyId: number, modelIds: number[]): Promise<void> {
    return firstValueFrom(this.http.put<void>(`/api/admin/api-keys/${keyId}/model-permissions`, { model_ids: modelIds }));
  }

  setApiKeyProviderPermissions(keyId: number, providerIds: number[]): Promise<void> {
    return firstValueFrom(this.http.put<void>(`/api/admin/api-keys/${keyId}/provider-permissions`, { provider_ids: providerIds }));
  }

  async createApiKey(teamId: number, payload: CreateApiKeyPayload): Promise<{ id: number; key_value: string }> {
    const res = await firstValueFrom(
      this.http.post<{ id: number; api_key: string }>(`/api/admin/teams/${teamId}/api-keys`, payload),
    );
    return { id: res.id, key_value: res.api_key };
  }

  rotateApiKey(keyId: number): Promise<{ result: string; api_key: string }> {
    return firstValueFrom(
      this.http.post<{ result: string; api_key: string }>(`/api/admin/api-keys/${keyId}/rotate`, {}),
    );
  }

  deleteApiKey(keyId: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`/api/admin/api-keys/${keyId}`));
  }

  getMyTeams(): Promise<MyTeam[]> {
    return firstValueFrom(this.http.get<MyTeam[]>('/api/teams/mine'));
  }
}
