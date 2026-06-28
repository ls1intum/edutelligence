import {
  Component,
  Input,
  Output,
  EventEmitter,
  computed,
  signal,
  inject,
  ChangeDetectionStrategy,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ModalFormComponent } from '../../../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { AuthService } from '../../../../core/auth/services/auth.service';
import {
  TeamDetail,
  TeamMember,
  AdminUser,
  TeamApiKey,
} from '../../../../shared/models/team.model';
import { SearchInputComponent } from '../../../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import { ApiKeyModalComponent } from '../../api-key-modal/api-key-modal';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';
import { IconTileComponent } from '../../../../shared/components/icon-tile/icon-tile';
import { buildKeyModelGroups, KeyModelGroup, ProviderInfo } from '../key-model-groups';

@Component({
  selector: 'app-members-tab',
  standalone: true,
  imports: [
    FormsModule,
    ModalFormComponent,
    ModalConfirmComponent,
    SearchInputComponent,
    DataTableComponent,
    ApiKeyModalComponent,
    ErrorMessageComponent,
    IconTileComponent,
  ],
  templateUrl: './members-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './members-tab.scss',
})
export class MembersTabComponent {
  @Input() team!: TeamDetail;
  @Input() teamId!: number;
  @Input() members: TeamMember[] = [];
  @Input() apiKeys: TeamApiKey[] = [];
  @Input() isLogosAdmin = false;
  @Input() canEdit = false;
  @Output() refresh = new EventEmitter<void>();

  private teamService = inject(TeamManagementService);
  private auth = inject(AuthService);

  isLogosAdminSignal = computed(() => this.auth.currentUser()?.role === 'logos_admin');

  get owners(): TeamMember[] {
    return this.members.filter((m) => m.is_owner);
  }
  get regulars(): TeamMember[] {
    return this.members.filter((m) => !m.is_owner);
  }

  avatarLetter(username: string): string {
    return (username.charAt(0) || '?').toUpperCase();
  }

  formatBudget(mc: number | null): string {
    if (mc === null || mc === undefined) return '-';
    if (mc < 0) return '∞';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(
      mc / 100_000_000,
    );
  }

  formatLimit(v: number | null): string {
    if (v === null || v === undefined || v < 0) return '∞';
    if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
    return `${v}`;
  }

  devKeyForUser(userId: number): TeamApiKey | undefined {
    return this.apiKeys.find((k) => k.user_id === userId && k.key_type === 'developer');
  }

  effectiveBudget(key: TeamApiKey): number | null {
    const sv = key.settings?.budget_limit_micro_cents;
    if (sv != null && sv >= 0) return sv;
    const kv = key.monthly_budget_micro_cents;
    if (kv != null && kv >= 0) return kv;
    return this.team?.default_monthly_budget_micro_cents ?? null;
  }

  // ── Budget usage (current month spend vs. effective limit) ─────────────────
  budgetUsed(key: TeamApiKey): number {
    return key.used_micro_cents ?? 0;
  }

  hasBudgetLimit(key: TeamApiKey): boolean {
    const limit = this.effectiveBudget(key);
    return limit != null && limit >= 0;
  }

  budgetPct(key: TeamApiKey): number {
    const limit = this.effectiveBudget(key);
    if (limit == null || limit <= 0) return 0;
    return Math.min((this.budgetUsed(key) / limit) * 100, 100);
  }

  budgetBarColor(key: TeamApiKey): string {
    return this.budgetPct(key) >= 90
      ? 'rgb(var(--color-error))'
      : 'rgb(var(--color-primary-500))';
  }

  effectiveCloudRpm(key: TeamApiKey): number | null {
    const v = key.settings?.cloud_rpm_limit ?? key.cloud_rpm_limit;
    if (v != null && v > 0) return v;
    return this.team?.default_cloud_rpm_limit ?? null;
  }

  effectiveCloudTpm(key: TeamApiKey): number | null {
    const v = key.settings?.cloud_tpm_limit ?? key.cloud_tpm_limit;
    if (v != null && v > 0) return v;
    return this.team?.default_cloud_tpm_limit ?? null;
  }

  effectiveLocalRpm(key: TeamApiKey): number | null {
    const v = key.settings?.local_rpm_limit ?? key.local_rpm_limit;
    if (v != null && v > 0) return v;
    return this.team?.default_local_rpm_limit ?? null;
  }

  effectiveLocalTpm(key: TeamApiKey): number | null {
    const v = key.settings?.local_tpm_limit ?? key.local_tpm_limit;
    if (v != null && v > 0) return v;
    return this.team?.default_local_tpm_limit ?? null;
  }

  // ── Expand state ──────────────────────────────────────────────────────────
  expandedKeyIds = signal<Set<number>>(new Set());
  loadingKeyIds = signal<Set<number>>(new Set());

  globalDataLoaded = false;
  private globalDataLoading = false;
  private keyPermCache = new Map<number, { providerIds: Set<number>; modelIds: Set<number> }>();

  allProviders = signal<ProviderInfo[]>([]);
  allModels = signal<{ id: number; name: string }[]>([]);
  teamProviderIds = signal<Set<number>>(new Set());
  teamModelIds = signal<Set<number>>(new Set());
  // providerId → set of model ids that provider serves
  private providerModelMap = new Map<number, Set<number>>();

  isExpanded(keyId: number): boolean {
    return this.expandedKeyIds().has(keyId);
  }
  isLoadingExpand(keyId: number): boolean {
    return this.loadingKeyIds().has(keyId);
  }

  toggleExpand(key: TeamApiKey): void {
    const next = new Set(this.expandedKeyIds());
    if (next.has(key.id)) {
      next.delete(key.id);
      this.expandedKeyIds.set(next);
      return;
    }
    next.add(key.id);
    this.expandedKeyIds.set(next);
    if (!this.globalDataLoaded) {
      if (!this.globalDataLoading) this.loadGlobalData(key);
    } else if (key.use_custom_permissions && !this.keyPermCache.has(key.id)) {
      this.loadKeyPerms(key.id);
    }
  }

  private async loadGlobalData(pending?: TeamApiKey): Promise<void> {
    this.globalDataLoading = true;
    try {
      const [providers, teamProviders, teamModels] = await Promise.all([
        this.teamService.getAllProviders(),
        this.teamService.getTeamProviderPermissions(this.teamId),
        this.teamService.getTeamModelPermissions(this.teamId),
      ]);

      this.allProviders.set(
        providers.map((p) => ({ id: p.id, name: p.name, isCloud: p.provider_type !== 'logosnode' })),
      );
      this.teamProviderIds.set(new Set(teamProviders));
      this.teamModelIds.set(new Set(teamModels));

      const modelById = new Map<number, string>();
      await Promise.all(
        providers.map(async (p) => {
          try {
            const ms = await this.teamService.getProviderModels(p.id);
            this.providerModelMap.set(p.id, new Set((ms ?? []).map((m) => m.model_id)));
            for (const m of ms ?? [])
              if (!modelById.has(m.model_id)) modelById.set(m.model_id, m.model_name);
          } catch {
            this.providerModelMap.set(p.id, new Set());
          }
        }),
      );
      this.allModels.set([...modelById.entries()].map(([id, name]) => ({ id, name })));
      this.globalDataLoaded = true;

      if (pending?.use_custom_permissions && !this.keyPermCache.has(pending.id)) {
        this.loadKeyPerms(pending.id);
      }
    } finally {
      this.globalDataLoading = false;
    }
  }

  private async loadKeyPerms(keyId: number): Promise<void> {
    const l = new Set(this.loadingKeyIds());
    l.add(keyId);
    this.loadingKeyIds.set(l);
    try {
      const [providerIds, modelIds] = await Promise.all([
        this.teamService.getApiKeyProviderPermissions(keyId),
        this.teamService.getApiKeyModelPermissions(keyId),
      ]);
      this.keyPermCache.set(keyId, {
        providerIds: new Set(providerIds),
        modelIds: new Set(modelIds),
      });
    } catch {
      // leave cache empty for this key
    } finally {
      const l2 = new Set(this.loadingKeyIds());
      l2.delete(keyId);
      this.loadingKeyIds.set(l2);
    }
  }

  getDisplayProviders(key: TeamApiKey): ProviderInfo[] {
    const ids = key.use_custom_permissions
      ? (this.keyPermCache.get(key.id)?.providerIds ?? new Set<number>())
      : this.teamProviderIds();
    return this.allProviders().filter((p) => ids.has(p.id));
  }

  getDisplayModels(key: TeamApiKey): { id: number; name: string }[] {
    const ids = key.use_custom_permissions
      ? (this.keyPermCache.get(key.id)?.modelIds ?? new Set<number>())
      : this.teamModelIds();
    return this.allModels().filter((m) => ids.has(m.id));
  }

  getModelGroups(key: TeamApiKey): KeyModelGroup[] {
    return buildKeyModelGroups(
      this.getDisplayProviders(key),
      this.getDisplayModels(key),
      this.providerModelMap,
    );
  }

  // ── add owner / member ────────────────────────────────────────────────────
  addOwnerOpen = signal(false);
  ownerSearch = signal('');
  allUsers = signal<AdminUser[]>([]);
  allUsersLoading = signal(false);
  addOwnerLoading = signal(false);
  addOwnerError = signal('');

  addMemberOpen = signal(false);
  memberSearch = signal('');
  addMemberLoading = signal(false);
  addMemberError = signal('');

  // ── remove confirmation modal ─────────────────────────────────────────────
  removeTarget = signal<TeamMember | null>(null);
  removeLoading = signal(false);
  removeError = signal(false);

  // Removing an owner demotes them to a regular member (is_owner = false) via
  // the logos_admin-only PATCH endpoint, so only expose it to logos_admins.
  // Ownership is editable even for Keycloak-managed owners (only removing the
  // membership is locked), so we intentionally do not gate this on m.managed.
  get canChangeRole(): boolean {
    return this.isLogosAdminSignal();
  }

  // ── dev-key modal ─────────────────────────────────────────────────────────
  selectedKey = signal<TeamApiKey | null>(null);
  keyModalOpen = signal(false);

  openKeyModal(key: TeamApiKey): void {
    this.selectedKey.set(key);
    this.keyModalOpen.set(true);
  }

  isExistingMember(userId: number): boolean {
    return this.members.some((m) => m.id === userId);
  }

  get filteredAddOwner(): AdminUser[] {
    const q = this.ownerSearch().toLowerCase();
    const ownerIds = new Set(this.owners.map((m) => m.id));
    const memberIds = new Set(this.regulars.map((m) => m.id));
    return this.allUsers().filter((u) => {
      if (ownerIds.has(u.id)) return false; // already an owner
      // Existing (non-owner) members can be promoted to owner from here, but
      // that goes through the logos_admin-only PATCH endpoint, so only offer
      // them to logos_admins; app_admin owners keep the add-new-user behaviour.
      if (memberIds.has(u.id) && !this.canChangeRole) return false;
      return u.username.toLowerCase().includes(q);
    });
  }

  get filteredAddMember(): AdminUser[] {
    const q = this.memberSearch().toLowerCase();
    const existing = new Set(this.members.map((m) => m.id));
    return this.allUsers().filter(
      (u) => !existing.has(u.id) && u.username.toLowerCase().includes(q),
    );
  }

  openAddOwner(): void {
    this.ownerSearch.set('');
    this.addOwnerError.set('');
    this.addOwnerOpen.set(true);
    if (this.allUsers().length === 0) this.fetchUsers();
  }

  openAddMember(): void {
    this.memberSearch.set('');
    this.addMemberError.set('');
    this.addMemberOpen.set(true);
    if (this.allUsers().length === 0) this.fetchUsers();
  }

  private async fetchUsers(): Promise<void> {
    this.allUsersLoading.set(true);
    try {
      const users = await this.teamService.getAllUsers();
      this.allUsers.set(users);
    } catch {
      // leave allUsers empty
    } finally {
      this.allUsersLoading.set(false);
    }
  }

  // Add Owner picker: promote an existing member, or add a brand-new user as
  // owner. Promoting flips is_owner via PATCH because adding an existing member
  // again (POST) would leave their ownership untouched.
  async pickAsOwner(userId: number): Promise<void> {
    this.addOwnerLoading.set(true);
    this.addOwnerError.set('');
    try {
      if (this.isExistingMember(userId)) {
        await this.teamService.updateTeamMemberOwner(this.teamId, userId, true);
      } else {
        await this.teamService.addTeamMember(this.teamId, userId, 'owner');
      }
      this.addOwnerOpen.set(false);
      this.refresh.emit();
    } catch {
      this.addOwnerError.set('Failed to add, please try again.');
    } finally {
      this.addOwnerLoading.set(false);
    }
  }

  async addMember(userId: number, role: 'owner' | 'member'): Promise<void> {
    const loading = role === 'owner' ? this.addOwnerLoading : this.addMemberLoading;
    const errSig = role === 'owner' ? this.addOwnerError : this.addMemberError;
    loading.set(true);
    errSig.set('');
    try {
      await this.teamService.addTeamMember(this.teamId, userId, role);
      if (role === 'owner') this.addOwnerOpen.set(false);
      else this.addMemberOpen.set(false);
      this.refresh.emit();
    } catch {
      errSig.set('Failed to add, please try again.');
    } finally {
      loading.set(false);
    }
  }

  openRemoveDialog(member: TeamMember): void {
    this.removeTarget.set(member);
    this.removeError.set(false);
  }

  closeRemoveDialog(): void {
    if (this.removeLoading()) return;
    this.removeTarget.set(null);
  }

  async confirmRemove(): Promise<void> {
    const member = this.removeTarget();
    if (!member || this.removeLoading()) return;
    this.removeLoading.set(true);
    this.removeError.set(false);
    try {
      if (member.is_owner) {
        // Removing an owner demotes them to a regular member (keeps membership).
        await this.teamService.updateTeamMemberOwner(this.teamId, member.id, false);
      } else {
        await this.teamService.removeTeamMember(this.teamId, member.id);
      }
      this.removeTarget.set(null);
      this.refresh.emit();
    } catch {
      this.removeError.set(true);
    } finally {
      this.removeLoading.set(false);
    }
  }
}
