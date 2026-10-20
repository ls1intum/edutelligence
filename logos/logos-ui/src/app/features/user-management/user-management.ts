import { Component, computed, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../core/auth/services/auth.service';
import {
  UserManagementService,
  CreateUserResult,
  ImportResult,
  ImportRow,
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
      // Membership changes flip nav visibility (Shell), so sync our own user.
      if (target.id === this.auth.currentUser()?.user_id && (toAdd.length > 0 || toRemove.length > 0)) {
        void this.auth.refreshUser();
      }
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
  // The file is parsed once on selection into raw columns + rows; the user then
  // maps which columns hold prename/name/email, picks the rows to import and
  // reviews the preview before anything is written. No team is assigned.
  importOpen = signal(false);
  importFileName = signal<string | null>(null);
  importColumns = signal<string[]>([]);
  importRows = signal<string[][]>([]);
  // Mapped column index per field, held as a string ('' = unset) so it binds
  // cleanly to a <select> whose option values are strings.
  importMapping = signal({ prename: '', name: '', email: '' });
  importSelected = signal<Set<number>>(new Set());
  importLoading = signal(false); // parsing (preview) or importing
  importPreviewLoading = signal(false);
  importError = signal<string | null>(null);
  importResult = signal<ImportResult | null>(null);

  knownEmails = computed(() => new Set(this.users().map((u) => (u.email ?? '').toLowerCase())));
  importReady = computed(() => this.importColumns().length > 0);

  importValid = computed(() => {
    const m = this.importMapping();
    return m.prename !== '' && m.name !== '' && m.email !== '' && this.importSelected().size > 0;
  });

  importSummary = computed(() => {
    let selected = 0;
    let toCreate = 0;
    let existing = 0;
    this.importSelected().forEach((idx) => {
      selected++;
      if (this.rowStatus(idx) === 'existing') existing++;
      else toCreate++;
    });
    return { selected, toCreate, existing, total: this.importRows().length };
  });

  openImportDialog(): void {
    this.importFileName.set(null);
    this.importColumns.set([]);
    this.importRows.set([]);
    this.importMapping.set({ prename: '', name: '', email: '' });
    this.importSelected.set(new Set());
    this.importLoading.set(false);
    this.importPreviewLoading.set(false);
    this.importError.set(null);
    this.importResult.set(null);
    this.importOpen.set(true);
  }

  closeImportDialog(): void {
    if (this.importLoading() || this.importPreviewLoading()) return;
    if (this.importResult()) void this.fetchUsers();
    this.importOpen.set(false);
  }

  pickCsvFile(): void {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv';
    input.onchange = (e: Event) => {
      const f = (e.target as HTMLInputElement).files?.[0];
      if (f) void this.loadImportPreview(f);
    };
    input.click();
  }

  private async loadImportPreview(file: File): Promise<void> {
    this.importPreviewLoading.set(true);
    this.importError.set(null);
    this.importResult.set(null);
    this.importFileName.set(file.name);
    try {
      const preview = await this.userSvc.previewImport(file);
      const columns = preview.columns ?? [];
      const rows = preview.rows ?? [];
      this.importColumns.set(columns);
      this.importRows.set(rows);
      this.importMapping.set(this.guessMapping(columns));
      // Everything is selected by default; the user de-selects what to skip.
      this.importSelected.set(new Set(rows.map((_, i) => i)));
    } catch (err: unknown) {
      const e = err as { error?: { detail?: string; error?: string } };
      this.importError.set(e?.error?.detail ?? e?.error?.error ?? 'Could not read that file.');
      this.importColumns.set([]);
      this.importRows.set([]);
    } finally {
      this.importPreviewLoading.set(false);
    }
  }

  /** Best-effort column matching so common exports map themselves automatically. */
  private guessMapping(columns: string[]): { prename: string; name: string; email: string } {
    const norm = columns.map((c) => c.trim().toLowerCase());
    const find = (patterns: RegExp[]): string => {
      for (const p of patterns) {
        const i = norm.findIndex((c) => p.test(c));
        if (i !== -1) return String(i);
      }
      return '';
    };
    return {
      prename: find([/first\s+name/, /given\s+name/, /prename/, /vorname/]),
      name: find([/last\s+name/, /surname/, /family\s+name/, /^name$/]),
      email: find([/e-?mail/]),
    };
  }

  setMappingField(field: 'prename' | 'name' | 'email', value: string): void {
    this.importMapping.update((m) => ({ ...m, [field]: value }));
  }

  /** Column index a field is mapped to, or -1 when unmapped. */
  colIndex(field: 'prename' | 'name' | 'email'): number {
    const v = this.importMapping()[field];
    return v === '' ? -1 : Number(v);
  }

  /** Grid template for the preview table: a select column, one per CSV column, then status. */
  importPreviewGrid(): string {
    const n = Math.max(this.importColumns().length, 1);
    return `48px repeat(${n}, minmax(120px, 1fr)) 96px`;
  }

  toggleRow(index: number): void {
    this.importSelected.update((s) => {
      const next = new Set(s);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  selectAllRows(): void {
    this.importSelected.set(new Set(this.importRows().map((_, i) => i)));
  }

  deselectAllRows(): void {
    this.importSelected.set(new Set());
  }

  isRowSelected(index: number): boolean {
    return this.importSelected().has(index);
  }

  /** "existing" when the mapped email already belongs to a known user, else "new". */
  rowStatus(index: number): 'existing' | 'new' {
    const cells = this.importRows()[index];
    const emailCol = this.colIndex('email');
    if (!cells || emailCol < 0) return 'new';
    const email = (cells[emailCol] ?? '').trim().toLowerCase();
    return email !== '' && this.knownEmails().has(email) ? 'existing' : 'new';
  }

  private buildImportRows(): ImportRow[] {
    const prenameCol = this.colIndex('prename');
    const nameCol = this.colIndex('name');
    const emailCol = this.colIndex('email');
    const cell = (cells: string[], i: number): string => (i >= 0 && i < cells.length ? (cells[i] ?? '') : '');
    const rows: ImportRow[] = [];
    [...this.importSelected()]
      .sort((a, b) => a - b)
      .forEach((idx) => {
        const cells = this.importRows()[idx];
        if (!cells) return;
        rows.push({ prename: cell(cells, prenameCol), name: cell(cells, nameCol), email: cell(cells, emailCol) });
      });
    return rows;
  }

  async submitImport(): Promise<void> {
    if (!this.importValid() || this.importLoading()) return;
    this.importLoading.set(true);
    this.importError.set(null);
    try {
      const result = await this.userSvc.importUsers(this.buildImportRows());
      this.importResult.set(result);
      await this.fetchUsers();
    } catch (err: unknown) {
      const e = err as { error?: { detail?: string; error?: string } };
      this.importError.set(e?.error?.detail ?? e?.error?.error ?? 'Import failed.');
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
}
