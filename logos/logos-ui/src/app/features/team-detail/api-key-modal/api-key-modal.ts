import {
  Component, Input, Output, EventEmitter, OnChanges, SimpleChanges,
  inject, signal, computed,
} from '@angular/core';
import { forkJoin } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { Dialog } from 'primeng/dialog';
import { TeamApiKey, TeamDetail, ApiKeyUpdatePayload } from '../../../shared/models/team.model';
import { TeamManagementService } from '../../../core/services/team-management.service';
import { SearchInputComponent } from '../../../shared/components/search-input/search-input';
import { ErrorMessageComponent } from '../../../shared/components/error-message/error-message';

const MICRO = 100_000_000;

function mcToDollars(mc: number | null | undefined): string {
  if (mc == null || mc < 0) return '';
  return (mc / MICRO).toFixed(2);
}

function dollarsToMc(s: string): number | null {
  const v = parseFloat(s.trim().replace(',', '.'));
  return isNaN(v) || v < 0 ? null : Math.round(v * MICRO);
}

function intOrMinus1(s: string): number {
  const v = parseInt(s.trim(), 10);
  return isNaN(v) || v <= 0 ? -1 : v;
}

@Component({
  selector: 'app-api-key-modal',
  standalone: true,
  imports: [FormsModule, Dialog, SearchInputComponent, ErrorMessageComponent],
  templateUrl: './api-key-modal.html',
  styleUrl: './api-key-modal.scss',
})
export class ApiKeyModalComponent implements OnChanges {
  @Input() visible = false;
  @Input() key: TeamApiKey | null = null;
  @Input() teamId!: number;
  @Input() canEdit = false;
  @Input() isLogosAdmin = false;
  @Input() team: TeamDetail | null = null;

  @Output() closed = new EventEmitter<void>();
  @Output() saved  = new EventEmitter<void>();

  private svc = inject(TeamManagementService);

  // ── form ─────────────────────────────────────────────────────────────────
  fBudget   = signal('');
  fCloudRpm = signal('');
  fCloudTpm = signal('');
  fLocalRpm = signal('');
  fLocalTpm = signal('');
  fEnv      = signal('');
  fPriority = signal('0');
  fLog      = signal<'BILLING' | 'FULL'>('BILLING');
  fCustom   = signal(false);

  // ── data ──────────────────────────────────────────────────────────────────
  allProviders        = signal<{ id: number; name: string }[]>([]);
  providerModelMap    = signal<Record<string, number[]>>({});
  allModels           = signal<{ id: number; name: string }[]>([]);

  selectedProviderIds = signal<Set<number>>(new Set());
  selectedModelIds    = signal<Set<number>>(new Set());
  teamProviderIds     = signal<Set<number>>(new Set());
  teamModelIds        = signal<Set<number>>(new Set());

  modelSearch    = signal('');
  providerSearch = signal('');
  permsLoading   = signal(false);

  filteredProviders = computed(() => {
    const q = this.providerSearch().toLowerCase();
    return this.allProviders().filter(p => p.name.toLowerCase().includes(q));
  });

  filteredModels = computed(() => {
    const q = this.modelSearch().toLowerCase();
    const activeProviders = this.fCustom() ? this.selectedProviderIds() : this.teamProviderIds();
    const allowedModelIds = new Set<number>();
    for (const pid of activeProviders) {
      (this.providerModelMap()[pid] ?? []).forEach(mid => allowedModelIds.add(mid));
    }
    return this.allModels().filter(m =>
      allowedModelIds.has(m.id) && m.name.toLowerCase().includes(q)
    );
  });

  // ── save / copy ───────────────────────────────────────────────────────────
  saveLoading = signal(false);
  saveError   = signal('');
  copied      = signal(false);

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['visible']?.currentValue && this.key) {
      this.initForm(this.key);
      this.loadPermissions(this.key.id);
    }
  }

  private initForm(key: TeamApiKey): void {
    const s = key.settings ?? {};
    this.fBudget.set(mcToDollars(s.budget_limit_micro_cents));
    this.fCloudRpm.set(s.cloud_rpm_limit && s.cloud_rpm_limit > 0 ? String(s.cloud_rpm_limit) : '');
    this.fCloudTpm.set(s.cloud_tpm_limit && s.cloud_tpm_limit > 0 ? String(s.cloud_tpm_limit) : '');
    this.fLocalRpm.set(s.local_rpm_limit && s.local_rpm_limit > 0 ? String(s.local_rpm_limit) : '');
    this.fLocalTpm.set(s.local_tpm_limit && s.local_tpm_limit > 0 ? String(s.local_tpm_limit) : '');
    this.fEnv.set(key.environment ?? '');
    this.fPriority.set(String(key.default_priority ?? 0));
    this.fLog.set(key.log ?? 'BILLING');
    this.fCustom.set(!!key.use_custom_permissions);
    this.saveError.set('');
    this.copied.set(false);
  }

  private loadPermissions(keyId: number): void {
    this.permsLoading.set(true);
    this.allProviders.set([]);
    this.allModels.set([]);
    this.providerModelMap.set({});
    this.selectedProviderIds.set(new Set());
    this.selectedModelIds.set(new Set());
    this.teamProviderIds.set(new Set());
    this.teamModelIds.set(new Set());

    forkJoin({
      providers:        this.svc.getAllProviders(),
      keyProviderIds:   this.svc.getApiKeyProviderPermissions(keyId),
      keyModelIds:      this.svc.getApiKeyModelPermissions(keyId),
      teamProviderIds:  this.svc.getTeamProviderPermissions(this.teamId),
      teamModelIds:     this.svc.getTeamModelPermissions(this.teamId),
    }).subscribe({
      next: async ({ providers, keyProviderIds, keyModelIds, teamProviderIds, teamModelIds }) => {
        this.allProviders.set(providers.map(p => ({ id: p.id, name: p.name })));
        this.selectedProviderIds.set(new Set(keyProviderIds));
        this.selectedModelIds.set(new Set(keyModelIds));
        this.teamProviderIds.set(new Set(teamProviderIds));
        this.teamModelIds.set(new Set(teamModelIds));

        // Fetch provider→model data once, build both the map and the model list
        const map: Record<string, number[]> = {};
        const modelById = new Map<number, string>();
        await Promise.all(providers.map(async p => {
          try {
            const models = await this.svc.getProviderModels(p.id).toPromise();
            map[p.id] = (models ?? []).map(m => m.model_id);
            for (const m of (models ?? [])) {
              if (!modelById.has(m.model_id)) modelById.set(m.model_id, m.model_name);
            }
          } catch {
            map[p.id] = [];
          }
        }));
        this.providerModelMap.set(map);
        this.allModels.set([...modelById.entries()].map(([id, name]) => ({ id, name })));
        this.permsLoading.set(false);
      },
      error: () => this.permsLoading.set(false),
    });
  }

  toggleModel(id: number): void {
    const s = new Set(this.selectedModelIds());
    s.has(id) ? s.delete(id) : s.add(id);
    this.selectedModelIds.set(s);
  }

  toggleProvider(id: number): void {
    const s = new Set(this.selectedProviderIds());
    s.has(id) ? s.delete(id) : s.add(id);
    this.selectedProviderIds.set(s);
  }

  isModelSelected(id: number): boolean    { return this.selectedModelIds().has(id); }
  isProviderSelected(id: number): boolean { return this.selectedProviderIds().has(id); }

  async copyKey(): Promise<void> {
    const v = this.key?.key_value;
    if (!v) return;
    await navigator.clipboard.writeText(v);
    this.copied.set(true);
    setTimeout(() => this.copied.set(false), 2000);
  }

  maskedKey(): string {
    const v = this.key?.key_value;
    if (!v) return '••••••••••••••••••••';
    return `${v.substring(0, 14)}••••••••••••••`;
  }

  formatDollars(mc: number | null | undefined): string {
    if (mc == null) return '-';
    if (mc < 0) return 'Unlimited';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(mc / MICRO);
  }

  formatLimit(v: number | null | undefined): string {
    if (v == null || v < 0) return '∞';
    if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
    return `${v}`;
  }

  formatUsed(mc: number | undefined): string {
    if (!mc) return '$0.00';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(mc / MICRO);
  }

  dollarsToMc = dollarsToMc;

  get dialogHeader(): string {
    return this.key?.key_type === 'developer' ? 'Developer Key Settings' : 'Service Key Settings';
  }

  close(): void {
    if (this.saveLoading()) return;
    this.closed.emit();
  }

  save(): void {
    const key = this.key;
    if (!key || this.saveLoading()) return;

    this.saveLoading.set(true);
    this.saveError.set('');

    const payload: ApiKeyUpdatePayload = {
      environment:              key.key_type === 'developer' ? '' : this.fEnv().trim(),
      default_priority:         parseInt(this.fPriority(), 10) || 0,
      log:                      this.fLog(),
      use_custom_permissions:   this.fCustom(),
      budget_limit_micro_cents: this.fBudget().trim() ? (dollarsToMc(this.fBudget()) ?? -1) : -1,
      cloud_rpm_limit:          intOrMinus1(this.fCloudRpm()),
      cloud_tpm_limit:          intOrMinus1(this.fCloudTpm()),
      local_rpm_limit:          intOrMinus1(this.fLocalRpm()),
      local_tpm_limit:          intOrMinus1(this.fLocalTpm()),
    };

    const ops: Array<ReturnType<typeof this.svc.updateApiKey>> = [
      this.svc.updateApiKey(key.id, payload),
    ];

    if (this.fCustom()) {
      if (this.isLogosAdmin) {
        ops.push(this.svc.setApiKeyProviderPermissions(key.id, [...this.selectedProviderIds()]));
      }
      ops.push(this.svc.setApiKeyModelPermissions(key.id, [...this.selectedModelIds()]));
    }

    forkJoin(ops).subscribe({
      next: () => {
        this.saveLoading.set(false);
        this.saved.emit();
        this.closed.emit();
      },
      error: () => {
        this.saveLoading.set(false);
        this.saveError.set('Failed to save, please try again.');
      },
    });
  }
}
