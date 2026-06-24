import {
  Component,
  computed,
  inject,
  signal,
  OnInit,
  effect,
  ChangeDetectionStrategy,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ModalFormComponent } from '../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';
import { AuthService } from '../../core/auth/services/auth.service';
import { TeamManagementService } from '../../core/services/team-management.service';
import { Team, AdminUser } from '../../shared/models/team.model';
import { SearchInputComponent } from '../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { IconTileComponent } from '../../shared/components/icon-tile/icon-tile';

@Component({
  selector: 'app-team-management',
  standalone: true,
  imports: [
    FormsModule,
    ModalFormComponent,
    ModalConfirmComponent,
    SearchInputComponent,
    DataTableComponent,
    ErrorMessageComponent,
    IconTileComponent,
  ],
  templateUrl: './team-management.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './team-management.scss',
})
export class TeamManagement implements OnInit {
  private auth = inject(AuthService);
  private router = inject(Router);
  private teamService = inject(TeamManagementService);

  // ── List state ──────────────────────────────────────────────────────────
  teams = signal<Team[]>([]);
  loading = signal(true);
  search = signal('');
  loadError = signal(false);

  // ── Admin users (for create modal owner picker) ─────────────────────────
  adminUsers = signal<AdminUser[]>([]);

  // ── Delete modal ────────────────────────────────────────────────────────
  deleteTarget = signal<Team | null>(null);
  deleteLoading = signal(false);
  deleteError = signal(false);

  // ── Create modal ────────────────────────────────────────────────────────
  createOpen = signal(false);
  createName = signal('');
  createOwnerIds = signal<number[]>([]);
  createLoading = signal(false);
  createError = signal('');

  // ── Computed ─────────────────────────────────────────────────────────────
  isLogosAdmin = computed(() => this.auth.currentUser()?.role === 'logos_admin');

  filteredTeams = computed(() => {
    const q = this.search().toLowerCase().trim();
    if (!q) return this.teams();
    return this.teams().filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.owners?.some((o) => o.username.toLowerCase().includes(q)),
    );
  });

  createValid = computed(() => this.createName().trim().length > 0);

  constructor() {
    effect(() => {
      if (this.isLogosAdmin() && this.adminUsers().length === 0) {
        this.fetchAdminUsers();
      }
    });
  }

  ngOnInit(): void {
    this.fetchTeams();
  }

  // ── Data fetching ─────────────────────────────────────────────────────────
  async fetchTeams(): Promise<void> {
    this.loading.set(true);
    this.loadError.set(false);
    try {
      const teams = await this.teamService.getTeams();
      this.teams.set(teams);
    } catch {
      this.loadError.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  async fetchAdminUsers(): Promise<void> {
    try {
      const users = await this.teamService.getAdminUsers();
      this.adminUsers.set(users);
    } catch {
      // silently ignore
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  ownerNames(team: Team): string {
    return team.owners?.length ? team.owners.map((o) => o.username).join(', ') : '-';
  }

  formatLimit(value: number | null): string {
    return value !== null ? value.toLocaleString() : '-';
  }

  toggleOwner(id: number): void {
    const current = this.createOwnerIds();
    if (current.includes(id)) {
      this.createOwnerIds.set(current.filter((x) => x !== id));
    } else {
      this.createOwnerIds.set([...current, id]);
    }
  }

  isOwnerSelected(id: number): boolean {
    return this.createOwnerIds().includes(id);
  }

  navigateToTeam(id: number): void {
    this.router.navigate(['/teams', id]);
  }

  // ── Delete flow ───────────────────────────────────────────────────────────
  openDeleteDialog(team: Team): void {
    this.deleteTarget.set(team);
    this.deleteError.set(false);
  }

  closeDeleteDialog(): void {
    if (this.deleteLoading()) return;
    this.deleteTarget.set(null);
    this.deleteError.set(false);
  }

  async confirmDelete(): Promise<void> {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    try {
      await this.teamService.deleteTeam(target.id);
      this.teams.update((list) => list.filter((t) => t.id !== target.id));
      this.deleteTarget.set(null);
    } catch {
      this.deleteError.set(true);
    } finally {
      this.deleteLoading.set(false);
    }
  }

  // ── Create flow ───────────────────────────────────────────────────────────
  openCreateDialog(): void {
    this.createName.set('');
    this.createOwnerIds.set([]);
    this.createError.set('');
    this.createOpen.set(true);
  }

  closeCreateDialog(): void {
    if (this.createLoading()) return;
    this.createOpen.set(false);
  }

  async submitCreate(): Promise<void> {
    if (!this.createValid() || this.createLoading()) return;
    this.createLoading.set(true);
    this.createError.set('');
    try {
      await this.teamService.createTeam(this.createName().trim(), this.createOwnerIds());
      this.createOpen.set(false);
      await this.fetchTeams();
    } catch {
      this.createError.set('Failed to create team, please try again.');
    } finally {
      this.createLoading.set(false);
    }
  }
}
