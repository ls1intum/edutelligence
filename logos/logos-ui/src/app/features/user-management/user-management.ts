import { Component, computed, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../core/auth/services/auth.service';
import {
  UserManagementService,
  CreateUserResult,
  ImportResult,
} from '../../core/services/user-management.service';
import { TeamManagementService } from '../../core/services/team-management.service';
import { PlatformUser } from '../../shared/models/platform-user.model';
import { UserRole } from '../../core/auth/models/user.model';
import { Team } from '../../shared/models/team.model';
import { ALL_ROLES, ROLE_LABELS } from '../../shared/constants/roles';
import { RoleBadgeComponent } from '../../shared/components/role-badge/role-badge';
import { IconTileComponent } from '../../shared/components/icon-tile/icon-tile';
import { SearchInputComponent } from '../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ModalFormComponent } from '../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';

const EMPTY_CREATE = { prename: '', name: '', email: '', role: 'app_developer' as UserRole };
const EMPTY_EDIT = { prename: '', name: '', email: '' };

@Component({
  selector: 'app-user-management',
  standalone: true,
  imports: [
    FormsModule,
    RoleBadgeComponent,
    IconTileComponent,
    SearchInputComponent,
    DataTableComponent,
    ModalFormComponent,
    ModalConfirmComponent,
    ErrorMessageComponent,
  ],
  templateUrl: './user-management.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './user-management.scss',
})
export class UserManagement {
  auth = inject(AuthService);
  private userSvc = inject(UserManagementService);
  private teamSvc = inject(TeamManagementService);

  readonly allRoles = ALL_ROLES;
  readonly roleLabels = ROLE_LABELS;

  // ── List ────────────────────────────────────────────────────────────────
  users = signal<PlatformUser[]>([]);
  loading = signal(true);
  search = signal('');
  roleError = signal(false);

  isLogosAdmin = computed(() => this.auth.currentUser()?.role === 'logos_admin');
  isAdminOrAbove = computed(() => {
    const r = this.auth.currentUser()?.role;
    return r === 'logos_admin' || r === 'app_admin';
  });

  filteredUsers = computed(() => {
    const q = this.search().toLowerCase().trim();
    if (!q) return this.users();
    return this.users().filter(
      (u) =>
        (u.username ?? '').toLowerCase().includes(q) ||
        `${u.prename ?? ''} ${u.name ?? ''}`.toLowerCase().includes(q) ||
        (u.email ?? '').toLowerCase().includes(q),
    );
  });

  // ── Teams list (shared by both modals) ───────────────────────────────────
  allTeams = signal<Team[]>([]);
  teamsLoading = signal(false);

  constructor() {
    this.fetchUsers();
  }

  async fetchUsers(): Promise<void> {
    this.loading.set(true);
    try {
      const users = await this.userSvc.getUsers();
      this.users.set(users);
    } catch {
      // leave loading false, no-op on error
    } finally {
      this.loading.set(false);
    }
  }

  private async loadTeams(): Promise<void> {
    if (this.allTeams().length > 0) return;
    this.teamsLoading.set(true);
    try {
      const teams = await this.teamSvc.getTeams();
      this.allTeams.set(teams);
    } catch {
      // no-op
    } finally {
      this.teamsLoading.set(false);
    }
  }

  async handleRoleChange(userId: number, newRole: UserRole): Promise<void> {
    const previous = this.users();
    this.roleError.set(false);
    this.users.update((list) => list.map((u) => (u.id === userId ? { ...u, role: newRole } : u)));
    try {
      await this.userSvc.updateRole(userId, newRole);
    } catch {
      this.users.set(previous);
      this.roleError.set(true);
    }
  }

  userInitials(user: PlatformUser): string {
    return (
      `${user.prename?.[0] ?? ''}${user.name?.[0] ?? ''}`.toUpperCase() ||
      user.username.slice(0, 2).toUpperCase()
    );
  }

  teamNames(user: PlatformUser): string {
    return user.teams.length ? user.teams.map((t) => t.name).join(', ') : '-';
  }

  // ── Team picker helpers (shared) ─────────────────────────────────────────
  teamSearch = signal('');

  filteredTeamOptions = computed(() => {
    const q = this.teamSearch().toLowerCase();
    if (!q) return this.allTeams();
    return this.allTeams().filter((t) => t.name.toLowerCase().includes(q));
  });

  // ── Create user ─────────────────────────────────────────────────────────
  createOpen = signal(false);
  createForm = signal({ ...EMPTY_CREATE });
  createTeamIds = signal<number[]>([]);
  createLoading = signal(false);
  createError = signal('');
  createResult = signal<CreateUserResult | null>(null);
  copiedKeys = signal(false);

  createValid = computed(() => {
    const f = this.createForm();
    return f.prename.trim().length > 0 && f.name.trim().length > 0 && f.email.trim().length > 0;
  });

  openCreateDialog(): void {
    this.createForm.set({ ...EMPTY_CREATE });
    this.createTeamIds.set([]);
    this.createError.set('');
    this.createResult.set(null);
    this.copiedKeys.set(false);
    this.teamSearch.set('');
    this.createOpen.set(true);
    this.loadTeams();
  }

  closeCreateDialog(): void {
    if (this.createLoading()) return;
    this.createOpen.set(false);
  }

  updateCreateField(field: keyof typeof EMPTY_CREATE, value: string): void {
    this.createForm.update((f) => ({ ...f, [field]: value }));
  }

  toggleCreateTeam(id: number): void {
    this.createTeamIds.update((ids) =>
      ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id],
    );
  }

  isCreateTeamSelected(id: number): boolean {
    return this.createTeamIds().includes(id);
  }

  async submitCreate(): Promise<void> {
    if (!this.createValid() || this.createLoading()) return;
    this.createLoading.set(true);
    this.createError.set('');
    const f = this.createForm();
    try {
      const result = await this.userSvc.createUser({
        prename: f.prename,
        name: f.name,
        email: f.email,
        role: f.role,
        team_ids: this.createTeamIds(),
      });
      this.users.update((list) => [result, ...list]);
      this.createResult.set(result);
    } catch (err: unknown) {
      const detail = (err as { error?: { detail?: string } })?.error?.detail ?? 'Failed to create user.';
      this.createError.set(detail);
    } finally {
      this.createLoading.set(false);
    }
  }

  copyApiKeys(): void {
    const keys = this.createResult()?.logos_keys ?? [];
    navigator.clipboard.writeText(keys.join('\n')).then(() => {
      this.copiedKeys.set(true);
      setTimeout(() => this.copiedKeys.set(false), 2000);
    });
  }

  // ── Edit user ────────────────────────────────────────────────────────────
  editTarget = signal<PlatformUser | null>(null);
  editForm = signal({ ...EMPTY_EDIT });
  editTeamIds = signal<number[]>([]);
  editOrigTeamIds = signal<number[]>([]);
  editLoading = signal(false);
  editError = signal('');

  openEditDialog(user: PlatformUser): void {
    this.editTarget.set(user);
    this.editForm.set({
      prename: user.prename ?? '',
      name: user.name ?? '',
      email: user.email ?? '',
    });
    const currentIds = user.teams.map((t) => t.id);
    this.editTeamIds.set([...currentIds]);
    this.editOrigTeamIds.set([...currentIds]);
    this.editError.set('');
    this.teamSearch.set('');
    this.loadTeams();
  }

  closeEditDialog(): void {
    if (this.editLoading()) return;
    this.editTarget.set(null);
  }

  updateEditField(field: keyof typeof EMPTY_EDIT, value: string): void {
    this.editForm.update((f) => ({ ...f, [field]: value }));
  }

  toggleEditTeam(id: number): void {
    this.editTeamIds.update((ids) =>
      ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id],
    );
  }

  isEditTeamSelected(id: number): boolean {
    return this.editTeamIds().includes(id);
  }

  editValid = computed(() => {
    const f = this.editForm();
    return f.prename.trim().length > 0 && f.name.trim().length > 0;
  });

  async submitEdit(): Promise<void> {
    const target = this.editTarget();
    if (!target || !this.editValid() || this.editLoading()) return;
    this.editLoading.set(true);
    this.editError.set('');
    const f = this.editForm();
    const origIds = this.editOrigTeamIds();
    const newIds = this.editTeamIds();
    const toAdd = newIds.filter(id => !origIds.includes(id));
    const toRemove = origIds.filter(id => !newIds.includes(id));
    try {
      await this.userSvc.updateUserInfo(target.id, { prename: f.prename, name: f.name, email: f.email });
      await Promise.all([
        ...toAdd.map(tid => this.teamSvc.addTeamMember(tid, target.id, 'member')),
        ...toRemove.map(tid => this.teamSvc.removeTeamMember(tid, target.id)),
      ]);
      await this.fetchUsers();
      this.editTarget.set(null);
    } catch (err: unknown) {
      const detail = (err as { error?: { detail?: string } })?.error?.detail ?? 'Failed to save changes.';
      this.editError.set(detail);
    } finally {
      this.editLoading.set(false);
    }
  }

  // ── Delete user ──────────────────────────────────────────────────────────
  deleteTarget = signal<PlatformUser | null>(null);
  deleteLoading = signal(false);
  deleteError = signal(false);

  openDeleteDialog(user: PlatformUser): void {
    this.deleteTarget.set(user);
    this.deleteError.set(false);
  }

  closeDeleteDialog(): void {
    if (this.deleteLoading()) return;
    this.deleteTarget.set(null);
  }

  async confirmDelete(): Promise<void> {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    try {
      await this.userSvc.deleteUser(target.id);
      this.users.update((list) => list.filter((u) => u.id !== target.id));
      this.deleteTarget.set(null);
    } catch {
      this.deleteError.set(true);
    } finally {
      this.deleteLoading.set(false);
    }
  }

  // ── CSV Import ───────────────────────────────────────────────────────────
  importOpen = signal(false);
  importFile = signal<File | null>(null);
  importFileName = signal<string | null>(null);
  importLoading = signal(false);
  importError = signal<string | null>(null);
  importResult = signal<ImportResult | null>(null);
  importCopied = signal(false);

  openImportDialog(): void {
    this.importFile.set(null);
    this.importFileName.set(null);
    this.importLoading.set(false);
    this.importError.set(null);
    this.importResult.set(null);
    this.importCopied.set(false);
    this.importOpen.set(true);
  }

  closeImportDialog(): void {
    if (this.importLoading()) return;
    this.importOpen.set(false);
  }

  pickCsvFile(): void {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv';
    input.onchange = (e: Event) => {
      const f = (e.target as HTMLInputElement).files?.[0];
      if (f) {
        this.importFile.set(f);
        this.importFileName.set(f.name);
        this.importError.set(null);
        this.importResult.set(null);
      }
    };
    input.click();
  }

  async submitImport(): Promise<void> {
    const file = this.importFile();
    if (!file || this.importLoading()) return;
    this.importLoading.set(true);
    this.importError.set(null);
    try {
      const result = await this.userSvc.importUsers(file);
      this.importResult.set(result);
      await this.fetchUsers();
    } catch (err: unknown) {
      const e = err as { error?: { detail?: string; error?: string } };
      const msg = e?.error?.detail ?? e?.error?.error ?? 'Import failed.';
      this.importError.set(msg);
    } finally {
      this.importLoading.set(false);
    }
  }

  importStatusClass(status: string): string {
    return status === 'created'
      ? 'status-created'
      : status === 'existing'
        ? 'status-existing'
        : 'status-failed';
  }

  downloadImportCsv(): void {
    const result = this.importResult();
    if (!result) return;
    const header = ['email', 'username', 'apiKey', 'team', 'status', 'error'];
    const rows = result.rows.map((r) =>
      [r.email, r.username, r.apiKey, r.team, r.status, r.error ?? '']
        .map((v) => (/[",\n\r]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v))
        .join(','),
    );
    const csv = [header.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'import-credentials.csv';
    a.click();
    URL.revokeObjectURL(url);
  }

  copyImportCsv(): void {
    const result = this.importResult();
    if (!result) return;
    const header = 'email,username,apiKey,team,status,error';
    const rows = result.rows.map((r) =>
      [r.email, r.username, r.apiKey, r.team, r.status, r.error ?? ''].join(','),
    );
    navigator.clipboard.writeText([header, ...rows].join('\n')).then(() => {
      this.importCopied.set(true);
      setTimeout(() => this.importCopied.set(false), 2000);
    });
  }
}
