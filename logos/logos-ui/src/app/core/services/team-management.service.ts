import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
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
  getTeams(): Observable<Team[]> {
    return this.http.get<Team[]>('/api/teams');
  }

  createTeam(name: string, ownerIds: number[]): Observable<Team> {
    return this.http.post<Team>('/api/teams', { name, owner_ids: ownerIds });
  }

  deleteTeam(id: number): Observable<void> {
    return this.http.delete<void>(`/api/teams/${id}`);
  }

  getAdminUsers(): Observable<AdminUser[]> {
    return this.http.get<AdminUser[]>('/api/users/admins');
  }

  // ── Detail page ────────────────────────────────────────────────────────────
  getTeamWithMembers(teamId: number): Observable<TeamMembersResponse> {
    return this.http.get<TeamMembersResponse>(`/api/teams/${teamId}/members`);
  }

  renameTeam(teamId: number, name: string): Observable<{ name: string }> {
    return this.http.patch<{ name: string }>(`/api/teams/${teamId}/name`, { name });
  }

  updateTeamLimits(teamId: number, payload: TeamLimitsPayload): Observable<void> {
    return this.http.patch<void>(`/api/teams/${teamId}`, payload);
  }

  getTeamApiKeys(teamId: number): Observable<TeamApiKey[]> {
    return this.http.get<TeamApiKey[]>(`/api/admin/teams/${teamId}/api-keys`);
  }

  getTeamModelPermissions(teamId: number): Observable<number[]> {
    return this.http.get<number[]>(`/api/admin/teams/${teamId}/model-permissions`);
  }

  setTeamModelPermissions(teamId: number, modelIds: number[]): Observable<void> {
    return this.http.put<void>(`/api/admin/teams/${teamId}/model-permissions`, { model_ids: modelIds });
  }

  getTeamProviderPermissions(teamId: number): Observable<number[]> {
    return this.http.get<number[]>(`/api/admin/teams/${teamId}/provider-permissions`);
  }

  setTeamProviderPermissions(teamId: number, providerIds: number[]): Observable<void> {
    return this.http.put<void>(`/api/admin/teams/${teamId}/provider-permissions`, { provider_ids: providerIds });
  }

  getAllProviders(): Observable<ProviderItem[]> {
    return this.http.post<ProviderItem[]>('/api/logosdb/get_providers', {});
  }

  getProviderModels(providerId: number): Observable<ProviderModelItem[]> {
    return this.http.post<ProviderModelItem[]>('/api/logosdb/get_provider_models', { provider_id: providerId });
  }

  getAllUsers(): Observable<AdminUser[]> {
    return this.http.get<AdminUser[]>('/api/users');
  }

  addTeamMember(teamId: number, userId: number, role: 'owner' | 'member'): Observable<void> {
    const body: Record<string, unknown> = { user_id: userId };
    if (role === 'owner') body['is_owner'] = true;
    return this.http.post<void>(`/api/teams/${teamId}/members`, body);
  }

  removeTeamMember(teamId: number, userId: number): Observable<void> {
    return this.http.delete<void>(`/api/teams/${teamId}/members/${userId}`);
  }

  // ── API key editing ────────────────────────────────────────────────────────
  updateApiKey(keyId: number, payload: ApiKeyUpdatePayload): Observable<void> {
    return this.http.patch<void>(`/api/admin/api-keys/${keyId}`, payload);
  }

  getApiKeyModelPermissions(keyId: number): Observable<number[]> {
    return this.http.get<number[]>(`/api/admin/api-keys/${keyId}/model-permissions`);
  }

  getApiKeyProviderPermissions(keyId: number): Observable<number[]> {
    return this.http.get<number[]>(`/api/admin/api-keys/${keyId}/provider-permissions`);
  }

  setApiKeyModelPermissions(keyId: number, modelIds: number[]): Observable<void> {
    return this.http.put<void>(`/api/admin/api-keys/${keyId}/model-permissions`, { model_ids: modelIds });
  }

  setApiKeyProviderPermissions(keyId: number, providerIds: number[]): Observable<void> {
    return this.http.put<void>(`/api/admin/api-keys/${keyId}/provider-permissions`, { provider_ids: providerIds });
  }

  createApiKey(teamId: number, payload: CreateApiKeyPayload): Observable<TeamApiKey> {
    return this.http.post<TeamApiKey>(`/api/admin/teams/${teamId}/api-keys`, payload);
  }

  deleteApiKey(keyId: number): Observable<void> {
    return this.http.delete<void>(`/api/admin/api-keys/${keyId}`);
  }

  getMyTeams(): Observable<MyTeam[]> {
    return this.http.get<MyTeam[]>('/api/teams/mine');
  }
}
