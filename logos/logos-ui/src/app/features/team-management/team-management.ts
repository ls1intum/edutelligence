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
import {
  ApplicationKeyQueueRankEntry,
  Team,
  AdminUser,
  TeamApiKey,
  KeycloakGroupOption,
} from '../../shared/models/team.model';
import { SearchInputComponent } from '../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { IconTileComponent } from '../../shared/components/icon-tile/icon-tile';
import { userDisplayName, userMatchesQuery } from '../../shared/utils/user-display';
import { errorDetail } from '../../shared/utils/error-detail';

/** Application key available to add to the cross-team queue order. */
interface QueueKeyOption {
  api_key_id: number;
  key_name: string;
  team_id: number;
  team_name: string;
  environment?: string | null;
  default_priority?: number | null;
}

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
  createKeycloakGroup = signal('');
  createLoading = signal(false);
  createError = signal('');

  // ── Keycloak group picker (logos admins) ────────────────────────────────
  /** Realm groups and roles offered as suggestions; empty when the deployment
   *  has no Keycloak directory access, in which case the field stays free text. */
  keycloakGroups = signal<KeycloakGroupOption[]>([]);
  /** The deployment can read the realm; false means the field is free text only. */
  keycloakDirectoryAvailable = signal(false);

  // ── Team queue priority (logos_admin only) ──────────────────────────────
  /** Team ids with a priority PATCH in flight, one entry per team so
   *  overlapping saves on different rows don't unlock each other's
   *  selectors. */
  prioritySaving = signal<Set<number>>(new Set());
  priorityError = signal('');

  // ── Application key queue order (logos_admin only) ─────────────────────
  queueRanks = signal<ApplicationKeyQueueRankEntry[]>([]);
  queueAllKeys = signal<QueueKeyOption[]>([]);
  queueLoading = signal(false);
  queueSaving = signal(false);
  queueError = signal('');
  queueAddKeyId = signal<number | ''>('');
  private queueLoaded = false;

  // ── Computed ─────────────────────────────────────────────────────────────
  isLogosAdmin = computed(() => this.auth.currentUser()?.role === 'logos_admin');
  isAppAdmin = computed(() => this.auth.currentUser()?.role === 'app_admin');
  canCreateTeam = computed(() => this.isLogosAdmin() || this.isAppAdmin());

  filteredTeams = computed(() => {
    let list = this.teams();
    if (this.isAppAdmin()) {
      list = list.filter((t) => t.is_caller_owner);
    }
    const q = this.search().toLowerCase().trim();
    if (!q) return list;
    return list.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.owners?.some((o) => userMatchesQuery(o, q)),
    );
  });

  createValid = computed(() => this.createName().trim().length > 0);

  rankedKeyIds = computed(() => new Set(this.queueRanks().map((r) => r.api_key_id)));

  unrankedKeys = computed(() => {
    const ranked = this.rankedKeyIds();
    return this.queueAllKeys()
      .filter((k) => !ranked.has(k.api_key_id))
      .sort(
        (a, b) =>
          a.team_name.localeCompare(b.team_name) ||
          a.key_name.localeCompare(b.key_name) ||
          a.api_key_id - b.api_key_id,
      );
  });

  /** Suggestions minus the groups another team already holds — the link is unique. */
  availableKeycloakGroups = computed(() =>
    this.keycloakGroups().filter((g) => g.linked_team_id === null),
  );

  constructor() {
    effect(() => {
      if (this.canCreateTeam() && this.adminUsers().length === 0) {
        this.fetchAdminUsers();
      }
    });
    effect(() => {
      if (this.isLogosAdmin() && !this.queueLoaded && !this.queueLoading()) {
        void this.loadQueueOrder();
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

  /** Group suggestions for the create dialog; silently stays free text on failure. */
  async fetchKeycloakGroups(): Promise<void> {
    try {
      const directory = await this.teamService.getKeycloakGroups();
      this.keycloakDirectoryAvailable.set(directory.available);
      this.keycloakGroups.set(directory.available ? directory.groups : []);
    } catch {
      this.keycloakDirectoryAvailable.set(false);
      this.keycloakGroups.set([]);
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

  async loadQueueOrder(): Promise<void> {
    if (this.queueLoading() || this.queueSaving()) return;
    this.queueLoading.set(true);
    this.queueError.set('');
    try {
      const [ranks, teams] = await Promise.all([
        this.teamService.getApplicationKeyQueueRanks(),
        this.teams().length > 0 ? Promise.resolve(this.teams()) : this.teamService.getTeams(),
      ]);
      if (this.teams().length === 0) this.teams.set(teams);
      this.queueRanks.set(ranks);
      const keyLists = await Promise.all(
        teams.map(async (team) => {
          try {
            const keys = await this.teamService.getTeamApiKeys(team.id);
            return keys
              .filter((k) => (k.key_type ?? 'application') === 'application')
              .map((k) => this.toQueueOption(k, team));
          } catch {
            return [] as QueueKeyOption[];
          }
        }),
      );
      this.queueAllKeys.set(keyLists.flat());
    } catch {
      this.queueError.set('Failed to load application key queue order.');
    } finally {
      // Mark attempted so the constructor effect does not retry in a loop.
      this.queueLoaded = true;
      this.queueLoading.set(false);
    }
  }

  private toQueueOption(key: TeamApiKey, team: Team): QueueKeyOption {
    return {
      api_key_id: key.id,
      key_name: key.name,
      team_id: team.id,
      team_name: team.name,
      environment: key.environment,
      default_priority: key.default_priority,
    };
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  ownerNames(team: Team): string {
    return team.owners?.length ? team.owners.map((o) => userDisplayName(o)).join(', ') : '-';
  }

  displayName(u: AdminUser): string {
    return userDisplayName(u);
  }

  /**
   * Whether the field offers suggestions — a datalist gives no affordance of
   * its own, so the admin would otherwise not know the realm can be browsed.
   */
  groupPickerHint(): string {
    if (!this.keycloakDirectoryAvailable()) {
      return 'Type the name exactly as a login claim carries it (a group path without its leading /).';
    }
    const free = this.availableKeycloakGroups().length;
    return `Pick one of the ${free} unlinked groups and roles in the realm, or type another.`;
  }

  /** What the lock badge of a linked team explains on hover. */
  managedTitle(team: Team): string {
    return `Linked to the Keycloak group '${team.keycloak_group}'. Its members join on login and `
      + 'leave again once they are out of the group; the team cannot be renamed or deleted while '
      + 'the link is in place.';
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

  // ── Team queue priority ─────────────────────────────────────────────────
  /** Select options: Default (unset) plus every value the API accepts (1–10),
   *  with Low/Normal/High annotating the classic bucket values. */
  readonly priorityOptions: { value: string; label: string }[] = [
    { value: '', label: 'Default' },
    ...Array.from({ length: 10 }, (_, i): { value: string; label: string } => {
      const v = i + 1;
      const bucket: Record<number, string> = { 1: 'Low', 5: 'Normal', 10: 'High' };
      return { value: String(v), label: bucket[v] ? `${bucket[v]} (${v})` : String(v) };
    }),
  ];

  priorityLabel(team: Team): string {
    if (team.priority === null || team.priority === undefined) return 'Default';
    const known: Record<number, string> = { 1: 'Low', 5: 'Normal', 10: 'High' };
    return known[team.priority] ?? String(team.priority);
  }

  /** The option value (a string, matching `priorityOptions`) currently
   *  selected for the team's priority; '' = Default/unset. Selection is
   *  expressed on the <option> via [selected], not as [value] on the
   *  <select> — a [value] binding on the <select> is applied before the @for
   *  has produced any <option>, so the browser drops it and the select falls
   *  back to the first option (Default) on every render, e.g. after a reload. */
  priorityValue(team: Team): string {
    return team.priority === null || team.priority === undefined ? '' : String(team.priority);
  }

  /** Optimistic select change: rolls back and reports if the PATCH fails. */
  async changeTeamPriority(team: Team, value: string): Promise<void> {
    const priority = value === '' ? null : Number(value);
    const previous = team.priority;
    this.priorityError.set('');
    this.teams.update((list) => list.map((t) => (t.id === team.id ? { ...t, priority } : t)));
    this.prioritySaving.update((saving) => new Set(saving).add(team.id));
    try {
      await this.teamService.updateTeamPriority(team.id, priority);
    } catch {
      this.teams.update((list) => list.map((t) => (t.id === team.id ? { ...t, priority: previous } : t)));
      this.priorityError.set(`Failed to update the queue priority of '${team.name}'.`);
    } finally {
      // Unlock only this team's selector — other rows may still be saving.
      this.prioritySaving.update((saving) => {
        const next = new Set(saving);
        next.delete(team.id);
        return next;
      });
    }
  }

  // ── Application key queue order ─────────────────────────────────────────
  async moveQueueRank(index: number, dir: -1 | 1): Promise<void> {
    const list = [...this.queueRanks()];
    const j = index + dir;
    if (j < 0 || j >= list.length || this.queueSaving() || this.queueLoading()) return;
    [list[index], list[j]] = [list[j], list[index]];
    await this.saveQueueOrder(list.map((r) => r.api_key_id));
  }

  async removeQueueRank(apiKeyId: number): Promise<void> {
    if (this.queueSaving() || this.queueLoading()) return;
    const ids = this.queueRanks()
      .filter((r) => r.api_key_id !== apiKeyId)
      .map((r) => r.api_key_id);
    await this.saveQueueOrder(ids);
  }

  async addQueueRank(): Promise<void> {
    const id = this.queueAddKeyId();
    if (id === '' || this.queueSaving() || this.queueLoading()) return;
    if (this.rankedKeyIds().has(id)) return;
    await this.saveQueueOrder([...this.queueRanks().map((r) => r.api_key_id), id]);
    this.queueAddKeyId.set('');
  }

  private async saveQueueOrder(apiKeyIds: number[]): Promise<void> {
    this.queueSaving.set(true);
    this.queueError.set('');
    try {
      const ranks = await this.teamService.replaceApplicationKeyQueueRanks(apiKeyIds);
      this.queueRanks.set(ranks);
    } catch {
      this.queueError.set('Failed to update application key queue order.');
    } finally {
      this.queueSaving.set(false);
    }
  }

  queueKeyLabel(entry: ApplicationKeyQueueRankEntry | QueueKeyOption): string {
    const env = 'environment' in entry && entry.environment ? ` · ${entry.environment}` : '';
    const team = entry.team_name ?? 'unknown team';
    return `${entry.key_name}${env} (${team})`;
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
      // Membership changes flip nav visibility (Shell), so sync our own user.
      if (this.auth.currentUser()?.teams.some((t) => t.id === target.id) ?? false) void this.auth.refreshUser();
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
    this.createKeycloakGroup.set('');
    this.createError.set('');
    this.createOpen.set(true);
    if (this.isLogosAdmin()) void this.fetchKeycloakGroups();
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
      const group = this.isLogosAdmin() ? this.createKeycloakGroup().trim() : '';
      const team = await this.teamService.createTeam(
        this.createName().trim(),
        this.createOwnerIds(),
        group || null,
      );
      // Membership changes flip nav visibility (Shell), so sync our own user.
      const selfId = this.auth.currentUser()?.user_id;
      if (selfId !== undefined && this.createOwnerIds().includes(selfId)) void this.auth.refreshUser();
      this.createOpen.set(false);
      this.router.navigate(['/teams', team.id]);
    } catch (err) {
      this.createError.set(errorDetail(err) ?? 'Failed to create team, please try again.');
    } finally {
      this.createLoading.set(false);
    }
  }
}
