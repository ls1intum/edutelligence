import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { PlatformUser } from '../../shared/models/platform-user.model';
import { UserRole } from '../auth/models/user.model';

export interface CreateUserPayload {
  prename: string;
  name: string;
  email: string;
  role: UserRole;
  team_ids?: number[];
}

export interface CreateUserResult extends PlatformUser {
  logos_keys: string[];
}

export interface ImportPreview {
  columns: string[];
  rows: string[][];
}

export interface ImportRow {
  prename: string;
  name: string;
  email: string;
}

export interface ImportResult {
  summary: { created: number; existing: number; failed: number };
  rows: { email: string; username: string; status: string; error?: string }[];
}

@Injectable({ providedIn: 'root' })
export class UserManagementService {
  private http = inject(HttpClient);

  getUsers(): Promise<PlatformUser[]> {
    return firstValueFrom(this.http.get<PlatformUser[]>('/api/users'));
  }

  updateRole(userId: number, role: UserRole): Promise<PlatformUser> {
    return firstValueFrom(this.http.patch<PlatformUser>(`/api/users/${userId}/role`, { role }));
  }

  createUser(payload: CreateUserPayload): Promise<CreateUserResult> {
    return firstValueFrom(this.http.post<CreateUserResult>('/api/users', payload));
  }

  updateUserInfo(userId: number, payload: { prename: string; name: string; email: string }): Promise<PlatformUser> {
    return firstValueFrom(this.http.patch<PlatformUser>(`/api/users/${userId}`, payload));
  }

  deleteUser(userId: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`/api/users/${userId}`));
  }

  previewImport(file: File): Promise<ImportPreview> {
    const formData = new FormData();
    formData.append('file', file);
    return firstValueFrom(this.http.post<ImportPreview>('/api/users/import/preview', formData));
  }

  importUsers(rows: ImportRow[]): Promise<ImportResult> {
    return firstValueFrom(this.http.post<ImportResult>('/api/users/import', { rows }));
  }
}
