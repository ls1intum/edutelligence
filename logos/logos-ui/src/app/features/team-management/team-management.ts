import { Component, computed, inject, signal, OnInit, effect } from '@angular/core';
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
  imports: [FormsModule, ModalFormComponent, ModalConfirmComponent, SearchInputComponent, DataTableComponent, ErrorMessageComponent, IconTileComponent],
  templateUrl: './team-management.html',
  styleUrl: './team-management.scss',
})
export class TeamManagement implements OnInit {
  private auth = inject(AuthService);
  private router = inject(Router);
  private teamService = inject(TeamManagementService);

  // ── List state ──────────────────────────────────────────────────────────
  teams       = signal<Team[]>([]);
  loading     = signal(true);
  search      = signal('');
  loadError   = signal(false);

  // ── Admin users (for create modal owner picker) ─────────────────────────
  adminUsers  = signal<AdminUser[]>([]);

  // ── Delete modal ────────────────────────────────────────────────────────
  deleteTarget   = signal<Team | null>(null);
  deleteLoading  = signal(false);
  deleteError    = signal(false);

  // ── Create modal ────────────────────────────────────────────────────────
  createOpen     = signal(false);
  createName     = signal('');
  createOwnerIds = signal<number[]>([]);
  createLoading  = signal(false);
  createError    = signal('');

  // ── Computed ─────────────────────────────────────────────────────────────
  isLogosAdmin = computed(() => this.auth.currentUser()?.role === 'logos_admin');

  filteredTeams = computed(() => {
    const q = this.search().toLowerCase().trim();
    if (!q) return this.teams();
    return this.teams().filter(t =>
      t.name.toLowerCase().includes(q) ||
      t.owners?.some(o => o.username.toLowerCase().includes(q))
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
  fetchTeams(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.teamService.getTeams().subscribe({
      next: teams => { this.teams.set(teams); this.loading.set(false); },
      error: ()    => { this.loadError.set(true); this.loading.set(false); },
    });
  }

  fetchAdminUsers(): void {
    this.teamService.getAdminUsers().subscribe({
      next: users => this.adminUsers.set(users),
      error: ()   => {},
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  ownerNames(team: Team): string {
    return team.owners?.length ? team.owners.map(o => o.username).join(', ') : '-';
  }

  formatLimit(value: number | null): string {
    return value !== null ? value.toLocaleString() : '-';
  }

  toggleOwner(id: number): void {
    const current = this.createOwnerIds();
    if (current.includes(id)) {
      this.createOwnerIds.set(current.filter(x => x !== id));
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

  confirmDelete(): void {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    this.teamService.deleteTeam(target.id).subscribe({
      next: () => {
        this.teams.update(list => list.filter(t => t.id !== target.id));
        this.deleteLoading.set(false);
        this.deleteTarget.set(null);
      },
      error: () => {
        this.deleteLoading.set(false);
        this.deleteError.set(true);
      },
    });
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

  submitCreate(): void {
    if (!this.createValid() || this.createLoading()) return;
    this.createLoading.set(true);
    this.createError.set('');
    this.teamService.createTeam(this.createName().trim(), this.createOwnerIds()).subscribe({
      next: () => {
        this.fetchTeams();
        this.createLoading.set(false);
        this.createOpen.set(false);
      },
      error: () => {
        this.createLoading.set(false);
        this.createError.set('Failed to create team, please try again.');
      },
    });
  }
}
