import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
  Team, AdminUser, TeamDetail, TeamMember, TeamApiKey,
  ProviderItem, ProviderModelItem, TeamModelPermission, TeamLimitsPayload,
  ApiKeyUpdatePayload, CreateApiKeyPayload, MyTeam,
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

  getTeamApiKeys(teamId: number): Promise<TeamApiKey[]> {
    return firstValueFrom(this.http.get<TeamApiKey[]>(`/api/admin/teams/${teamId}/api-keys`));
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

  deleteApiKey(keyId: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`/api/admin/api-keys/${keyId}`));
  }

  getMyTeams(): Promise<MyTeam[]> {
    return firstValueFrom(this.http.get<MyTeam[]>('/api/teams/mine'));
  }
}
