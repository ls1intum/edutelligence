import {
  Component,
  Input,
  Output,
  EventEmitter,
  computed,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { TeamApiKey, TeamDetail, CreateApiKeyPayload } from '../../../../shared/models/team.model';
import { AuthService } from '../../../../core/auth/services/auth.service';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import { ApiKeyModalComponent } from '../../api-key-modal/api-key-modal';
import { ModalFormComponent } from '../../../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { FormsModule } from '@angular/forms';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';

const MICRO = 100_000_000;

@Component({
  selector: 'app-app-keys-tab',
  standalone: true,
  imports: [
    DataTableComponent,
    ApiKeyModalComponent,
    ModalFormComponent,
    ModalConfirmComponent,
    FormsModule,
    ErrorMessageComponent,
  ],
  templateUrl: './app-keys-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './app-keys-tab.scss',
})
export class AppKeysTabComponent {
  @Input() apiKeys: TeamApiKey[] = [];
  @Input() teamId!: number;
  @Input() canEdit = false;
  @Input() team: TeamDetail | null = null;

  private auth = inject(AuthService);
  private svc = inject(TeamManagementService);

  isLogosAdmin = computed(() => this.auth.currentUser()?.role === 'logos_admin');
  appKeys = computed(() => this.apiKeys.filter((k) => k.key_type !== 'developer'));

  @Output() refresh = new EventEmitter<void>();

  // ── Create dialog ──────────────────────────────────────────────────────────
  createOpen = signal(false);
  createLoading = signal(false);
  createError = signal('');
  cEnv = signal('prod');
  cPriority = signal('0');
  cBudget = signal('');
  cCloudRpm = signal('');
  cCloudTpm = signal('');
  cLocalRpm = signal('');
  cLocalTpm = signal('');

  selectedKey = signal<TeamApiKey | null>(null);
  modalOpen = signal(false);

  openModal(key: TeamApiKey): void {
    this.selectedKey.set(key);
    this.modalOpen.set(true);
  }

  private readonly MICRO = 100_000_000;

  defaultBudgetPlaceholder = computed(() => {
    const mc = this.team?.default_monthly_budget_micro_cents;
    return mc ? `Default: $${(mc / this.MICRO).toFixed(2)}` : 'Unlimited';
  });

  private parseMc(s: string): number | null {
    const v = parseFloat(s.trim().replace(',', '.'));
    return isNaN(v) || v < 0 ? null : Math.round(v * this.MICRO);
  }

  private parseLimit(s: string): number | null {
    const v = parseInt(s.trim(), 10);
    return isNaN(v) || v <= 0 ? null : v;
  }

  resetCreate(): void {
    this.cEnv.set('prod');
    this.cPriority.set('0');
    this.cBudget.set('');
    this.cCloudRpm.set('');
    this.cCloudTpm.set('');
    this.cLocalRpm.set('');
    this.cLocalTpm.set('');
    this.createError.set('');
  }

  async submitCreate(): Promise<void> {
    const env = this.cEnv().trim();
    if (!env || this.createLoading()) return;
    this.createLoading.set(true);
    this.createError.set('');

    const payload: CreateApiKeyPayload = {
      name: `${this.team?.name ?? 'team'}-${env}`,
      key_type: 'application',
      environment: env,
      default_priority: parseInt(this.cPriority(), 10) || 0,
      log: 'BILLING',
      settings: {
        budget_limit_micro_cents: this.parseMc(this.cBudget()),
        cloud_rpm_limit: this.parseLimit(this.cCloudRpm()),
        cloud_tpm_limit: this.parseLimit(this.cCloudTpm()),
        local_rpm_limit: this.parseLimit(this.cLocalRpm()),
        local_tpm_limit: this.parseLimit(this.cLocalTpm()),
      },
    };

    try {
      const newKey = await this.svc.createApiKey(this.teamId, payload);
      this.createOpen.set(false);
      this.resetCreate();
      this.openModal(newKey);
      this.refresh.emit();
    } catch (err: any) {
      const msg =
        err?.error?.detail || err?.error?.message || 'Failed to create application key.';
      this.createError.set(msg);
    } finally {
      this.createLoading.set(false);
    }
  }

  // ── Delete dialog ──────────────────────────────────────────────────────────
  pendingDeleteKey = signal<TeamApiKey | null>(null);
  deleteLoading = signal(false);
  deleteError = signal('');

  async submitDelete(): Promise<void> {
    const key = this.pendingDeleteKey();
    if (!key || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set('');

    try {
      await this.svc.deleteApiKey(key.id);
      this.pendingDeleteKey.set(null);
      this.refresh.emit();
    } catch {
      this.deleteError.set('Failed to delete key, please try again.');
    } finally {
      this.deleteLoading.set(false);
    }
  }

  // ── Expand state ──────────────────────────────────────────────────────────
  expandedKeyIds = signal<Set<number>>(new Set());
  loadingKeyIds = signal<Set<number>>(new Set());

  globalDataLoaded = false;
  private globalDataLoading = false;
  private keyPermCache = new Map<number, { providerIds: Set<number>; modelIds: Set<number> }>();

  allProviders = signal<{ id: number; name: string }[]>([]);
  allModels = signal<{ id: number; name: string }[]>([]);
  teamProviderIds = signal<Set<number>>(new Set());
  teamModelIds = signal<Set<number>>(new Set());

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
        this.svc.getAllProviders(),
        this.svc.getTeamProviderPermissions(this.teamId),
        this.svc.getTeamModelPermissions(this.teamId),
      ]);

      this.allProviders.set(providers.map((p) => ({ id: p.id, name: p.name })));
      this.teamProviderIds.set(new Set(teamProviders));
      this.teamModelIds.set(new Set(teamModels));

      const map: Record<number, number[]> = {};
      const modelById = new Map<number, string>();
      await Promise.all(
        providers.map(async (p) => {
          try {
            const ms = await this.svc.getProviderModels(p.id);
            map[p.id] = (ms ?? []).map((m) => m.model_id);
            for (const m of ms ?? [])
              if (!modelById.has(m.model_id)) modelById.set(m.model_id, m.model_name);
          } catch {
            map[p.id] = [];
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
        this.svc.getApiKeyProviderPermissions(keyId),
        this.svc.getApiKeyModelPermissions(keyId),
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

  getDisplayProviders(key: TeamApiKey): { id: number; name: string }[] {
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

  // ── Effective values (key override → team default → null) ─────────────────
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

  // ── Formatting ────────────────────────────────────────────────────────────
  formatLimit(v: number | null): string {
    if (v === null || v === undefined || v < 0) return '∞';
    if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
    return `${v}`;
  }

  formatBudget(mc: number | null): string {
    if (mc === null || mc === undefined || mc < 0) return '∞';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(
      mc / MICRO,
    );
  }
}
