import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { PlatformUser } from '../../shared/models/platform-user.model';
import { UserRole } from '../auth/models/user.model';

@Injectable({ providedIn: 'root' })
export class UserManagementService {
  private http = inject(HttpClient);

  getUsers(): Observable<PlatformUser[]> {
    return this.http.get<PlatformUser[]>('/api/users');
  }

  updateRole(userId: number, role: UserRole): Observable<PlatformUser> {
    return this.http.patch<PlatformUser>(`/api/users/${userId}/role`, { role });
  }
}
