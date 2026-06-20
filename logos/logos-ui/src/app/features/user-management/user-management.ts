import { Component, computed, inject, signal } from '@angular/core';
import { AuthService } from '../../core/auth/services/auth.service';
import { UserManagementService } from '../../core/services/user-management.service';
import { PlatformUser } from '../../shared/models/platform-user.model';
import { UserRole } from '../../core/auth/models/user.model';
import { RoleBadgeComponent } from '../../shared/components/role-badge/role-badge';
import { UserAvatarComponent } from '../../shared/components/user-avatar/user-avatar';
import { SearchInputComponent } from '../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../shared/components/data-table/data-table';

@Component({
  selector: 'app-user-management',
  standalone: true,
  imports: [RoleBadgeComponent, UserAvatarComponent, SearchInputComponent, DataTableComponent],
  templateUrl: './user-management.html',
  styleUrl: './user-management.scss',
})
export class UserManagement {
  auth = inject(AuthService);
  private userMgmtService = inject(UserManagementService);

  users     = signal<PlatformUser[]>([]);
  loading   = signal(true);
  search    = signal('');
  roleError = signal(false);

  isLogosAdmin = computed(() => this.auth.currentUser()?.role === 'logos_admin');

  filteredUsers = computed(() => {
    const q = this.search().toLowerCase().trim();
    if (!q) return this.users();
    return this.users().filter(u =>
      (u.username ?? '').toLowerCase().includes(q) ||
      `${u.prename ?? ''} ${u.name ?? ''}`.toLowerCase().includes(q) ||
      (u.email ?? '').toLowerCase().includes(q)
    );
  });

  constructor() { this.fetchUsers(); }

  fetchUsers(): void {
    this.loading.set(true);
    this.userMgmtService.getUsers().subscribe({
      next: users => { this.users.set(users); this.loading.set(false); },
      error: ()   => { this.loading.set(false); },
    });
  }

  handleRoleChange(userId: number, newRole: UserRole): void {
    const previous = this.users();
    this.roleError.set(false);
    this.users.update(list => list.map(u => u.id === userId ? { ...u, role: newRole } : u));
    this.userMgmtService.updateRole(userId, newRole).subscribe({
      error: () => { this.users.set(previous); this.roleError.set(true); },
    });
  }

  teamNames(user: PlatformUser): string {
    return user.teams.length ? user.teams.map(t => t.name).join(', ') : '-';
  }
}
