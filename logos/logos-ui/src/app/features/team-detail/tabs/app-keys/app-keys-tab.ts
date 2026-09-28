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
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import { ApiKeyModalComponent } from '../../api-key-modal/api-key-modal';
import { ModalFormComponent } from '../../../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { FormsModule } from '@angular/forms';
import {
  CdkDrag,
  CdkDragDrop,
  CdkDragHandle,
  CdkDragPlaceholder,
  CdkDropList,
  moveItemInArray,
} from '@angular/cdk/drag-drop';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';
import { buildKeyModelGroups, KeyModelGroup, ProviderInfo } from '../key-model-groups';
import { isInteractiveClick } from '../../../../shared/utils/interactive-click';
import {
  KeySla,
  SLA_OPTIONS,
  SLA_PRIORITY,
  DEFAULT_SLA,
  slaHint,
  slaLabel,
  slaOfPriority,
  slaRank,
} from './key-sla';
import { loadKeyOrder, orderRank, saveKeyOrder } from './key-order';

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
    CdkDropList,
    CdkDrag,
    CdkDragHandle,
    CdkDragPlaceholder,
  ],
  templateUrl: './app-keys-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './app-keys-tab.scss',
})
export class AppKeysTabComponent {
  @Input() apiKeys: TeamApiKey[] = [];
  @Input() canEdit = false;
  @Input() team: TeamDetail | null = null;

  private _teamId!: number;

  @Input() set teamId(value: number) {
    this._teamId = value;
    this.manualOrder.set(loadKeyOrder(value));
  }

  get teamId(): number {
    return this._teamId;
  }

  private svc = inject(TeamManagementService);

  appKeys = computed(() => this.apiKeys.filter((k) => k.key_type !== 'developer'));

  @Output() refresh = new EventEmitter<void>();

  // ── SLA tier & manual order ────────────────────────────────────────────────
  readonly slaOptions = SLA_OPTIONS;
  readonly slaLabel = slaLabel;
  readonly slaHint = slaHint;

  /** Key ids in the drag-and-drop order, most recently persisted for this team. */
  manualOrder = signal<number[]>([]);
  /** Optimistic tiers for keys whose SLA change is in flight or already saved. */
  private slaOverrides = signal<Map<number, KeySla>>(new Map());
  slaSaving = signal<Set<number>>(new Set());
  slaError = signal('');

  /**
   * Application keys sorted by SLA first, then by the manual drag order.
   * The SLA is the only part the orchestrator sees, so it always outranks the
   * manual order rather than the other way round.
   */
  orderedKeys = computed(() => {
    const order = this.manualOrder();
    const keys = this.appKeys();
    const rankOf = new Map(keys.map((k, i) => [k.id, orderRank(order, k.id, i)]));
    return [...keys].sort((a, b) => {
      const tier = slaRank(this.slaOf(a)) - slaRank(this.slaOf(b));
      return tier !== 0 ? tier : (rankOf.get(a.id) ?? 0) - (rankOf.get(b.id) ?? 0);
    });
  });

  slaOf(key: TeamApiKey): KeySla {
    return this.slaOverrides().get(key.id) ?? slaOfPriority(key.default_priority);
  }

  /** True for the first row of an SLA tier, which draws the tier separator. */
  startsTier(index: number): boolean {
    const keys = this.orderedKeys();
    return index === 0 || this.slaOf(keys[index - 1]) !== this.slaOf(keys[index]);
  }

  /**
   * A stored priority that is neither the tier's own value nor 0 ("nothing
   * chosen yet"). The queue buckets 2..9 as NORMAL but still dequeues a 7
   * ahead of a plain 5, so the exact number is worth showing rather than
   * hiding behind the tier it rounds to.
   */
  rawPriorityNote(key: TeamApiKey): string | null {
    // While a change is in flight the stored value is still the old one, which
    // would read as a contradiction next to the tier already shown.
    if (this.slaSaving().has(key.id)) return null;
    const raw = key.default_priority ?? 0;
    if (raw === 0 || raw === SLA_PRIORITY[this.slaOf(key)]) return null;
    return String(raw);
  }

  async changeSla(key: TeamApiKey, sla: KeySla): Promise<void> {
    if (!this.canEdit || this.slaSaving().has(key.id) || this.slaOf(key) === sla) return;
    const previous = this.slaOverrides().get(key.id);
    this.slaError.set('');
    this.slaOverrides.update((m) => new Map(m).set(key.id, sla));
    this.slaSaving.update((s) => new Set(s).add(key.id));
    try {
      await this.svc.updateApiKey(key.id, { default_priority: SLA_PRIORITY[sla] });
      // Write through so a modal opened from the cached list shows the new
      // priority without waiting for the parent's refetch.
      key.default_priority = SLA_PRIORITY[sla];
    } catch {
      this.slaOverrides.update((m) => {
        const next = new Map(m);
        previous === undefined ? next.delete(key.id) : next.set(key.id, previous);
        return next;
      });
      this.slaError.set(`Failed to update the SLA of '${key.name}'.`);
    } finally {
      this.slaSaving.update((s) => {
        const next = new Set(s);
        next.delete(key.id);
        return next;
      });
    }
  }

  /**
   * A row dropped between two tiers joins the one above it, so dragging a key
   * upwards past a tier boundary raises its SLA and dragging it down lowers it.
   */
  private slaAtDropTarget(list: TeamApiKey[], index: number): KeySla {
    const above = index > 0 ? this.slaOf(list[index - 1]) : null;
    const below = index < list.length - 1 ? this.slaOf(list[index + 1]) : null;
    return above ?? below ?? this.slaOf(list[index]);
  }

  onDrop(event: CdkDragDrop<TeamApiKey[]>): Promise<void> {
    return this.moveTo(event.previousIndex, event.currentIndex);
  }

  /**
   * Keyboard equivalent of a drag, so the order (and with it the SLA a row
   * crosses into) is reachable without a pointer.
   */
  onHandleKeydown(event: KeyboardEvent, index: number): void {
    const delta = event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0;
    if (delta === 0) return;
    event.preventDefault();
    event.stopPropagation();
    void this.moveTo(index, index + delta);
  }

  private async moveTo(from: number, to: number): Promise<void> {
    const list = [...this.orderedKeys()];
    if (!this.canEdit || from === to || to < 0 || to >= list.length) return;
    moveItemInArray(list, from, to);
    const moved = list[to];
    const target = this.slaAtDropTarget(list, to);

    const ids = list.map((k) => k.id);
    this.manualOrder.set(ids);
    saveKeyOrder(this.teamId, ids);

    await this.changeSla(moved, target);
  }

  // ── Create dialog ──────────────────────────────────────────────────────────
  createOpen = signal(false);
  createLoading = signal(false);
  createError = signal('');
  cEnv = signal('prod');
  cSla = signal<KeySla>(DEFAULT_SLA);
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
    this.cSla.set(DEFAULT_SLA);
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
      default_priority: SLA_PRIORITY[this.cSla()],
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
      const { id, key_value } = await this.svc.createApiKey(this.teamId, payload);
      this.createOpen.set(false);
      this.resetCreate();
      this.openModal({
        id,
        key_value,
        name: payload.name,
        key_type: payload.key_type,
        environment: payload.environment,
        default_priority: payload.default_priority,
        log: payload.log,
        monthly_budget_micro_cents: payload.settings.budget_limit_micro_cents,
        cloud_rpm_limit: payload.settings.cloud_rpm_limit,
        cloud_tpm_limit: payload.settings.cloud_tpm_limit,
        local_rpm_limit: payload.settings.local_rpm_limit,
        local_tpm_limit: payload.settings.local_tpm_limit,
      });
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

  onRowClick(event: Event, key: TeamApiKey): void {
    if (isInteractiveClick(event)) return;
    this.toggleExpand(key);
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

      this.allProviders.set(
        providers.map((p) => ({ id: p.id, name: p.name, isCloud: p.provider_type !== 'logosnode' })),
      );
      this.teamProviderIds.set(new Set(teamProviders));
      this.teamModelIds.set(new Set(teamModels));

      const modelById = new Map<number, string>();
      await Promise.all(
        providers.map(async (p) => {
          try {
            const ms = await this.svc.getProviderModels(p.id);
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
