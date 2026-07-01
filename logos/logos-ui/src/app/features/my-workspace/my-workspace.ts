import { Component, OnInit, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ModalFormComponent } from '../../shared/components/modal/modal-form/modal-form';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { IconTileComponent } from '../../shared/components/icon-tile/icon-tile';
import { MyKeysService } from '../../core/services/my-keys.service';
import { TeamManagementService } from '../../core/services/team-management.service';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';
import { MyTeam } from '../../shared/models/team.model';

interface TeamWorkspace {
  team: MyTeam;
  keys: MyKey[];
}

interface ModelGroup {
  model_name: string;
  providers: string[];
  hasCloud: boolean;
  hasLocal: boolean;
}

@Component({
  selector: 'app-my-workspace',
  standalone: true,
  imports: [CommonModule, ModalFormComponent, ErrorMessageComponent, IconTileComponent],
  templateUrl: './my-workspace.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './my-workspace.scss',
})
export class MyWorkspace implements OnInit {
  private keysService = inject(MyKeysService);
  private teamService = inject(TeamManagementService);

  workspaces = signal<TeamWorkspace[]>([]);
  loading = signal(true);
  loadError = signal(false);

  expandedKeyIds = signal<Set<number>>(new Set());
  keyModels = signal<Map<number, ModelAccess[]>>(new Map());
  modelsLoading = signal<Set<number>>(new Set());
  modelsError = signal<Set<number>>(new Set());

  logChangeTarget = signal<{ key: MyKey; newLog: 'BILLING' | 'FULL' } | null>(null);
  logChangeLoading = signal(false);
  logChangeError = signal(false);

  copiedKeyId = signal<number | null>(null);

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    this.loadError.set(false);
    try {
      const [teams, keys] = await Promise.all([
        this.teamService.getMyTeams(),
        this.keysService.getMyKeys(),
      ]);
      const devKeys = keys.filter((k) => k.key_type?.toLowerCase() === 'developer');
      const byTeam = new Map<number, MyKey[]>();
      for (const k of devKeys) {
        const list = byTeam.get(k.team.id) ?? [];
        list.push(k);
        byTeam.set(k.team.id, list);
      }
      this.workspaces.set(teams.map((team) => ({ team, keys: byTeam.get(team.id) ?? [] })));
    } catch {
      this.loadError.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  // ── Team helpers ───────────────────────────────────────────────────────────
  ownersLabel(team: MyTeam): string {
    if (!team.owners?.length) return '—';
    const names = team.owners
      .map((o) => `${o.prename ?? ''} ${o.name ?? ''}`.trim())
      .filter((s) => s.length > 0);
    return names.length ? names.join(', ') : '—';
  }

  teamBudgetPercent(team: MyTeam): number {
    if (!team.team_monthly_budget_micro_cents) return 0;
    return Math.min(
      100,
      (team.budget_used_micro_cents / team.team_monthly_budget_micro_cents) * 100,
    );
  }

  // ── Money ──────────────────────────────────────────────────────────────────
  formatDollars(mc: number | null): string {
    if (mc == null) return '∞';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(
      mc / 100_000_000,
    );
  }

  // ── Key value / copy ───────────────────────────────────────────────────────
  maskedKey(keyValue: string): string {
    const prefix = keyValue.slice(0, 14);
    return `${prefix} · · · · · · · · ·`;
  }

  copyKey(key: MyKey): void {
    navigator.clipboard.writeText(key.key_value).then(() => {
      this.copiedKeyId.set(key.id);
      setTimeout(() => this.copiedKeyId.set(null), 2000);
    });
  }

  isCopied(keyId: number): boolean {
    return this.copiedKeyId() === keyId;
  }

  // ── Models expansion ───────────────────────────────────────────────────────
  toggleModels(key: MyKey): void {
    const expanded = new Set(this.expandedKeyIds());
    if (expanded.has(key.id)) {
      expanded.delete(key.id);
      this.expandedKeyIds.set(expanded);
      return;
    }
    expanded.add(key.id);
    this.expandedKeyIds.set(expanded);
    if (this.keyModels().has(key.id)) return;
    void this.loadKeyModels(key);
  }

  private async loadKeyModels(key: MyKey): Promise<void> {
    const loading = new Set(this.modelsLoading());
    loading.add(key.id);
    this.modelsLoading.set(loading);
    try {
      const models = await this.keysService.getKeyModels(key.id);
      this.keyModels.update((m) => { const n = new Map(m); n.set(key.id, models); return n; });
      this.modelsLoading.update((s) => { const n = new Set(s); n.delete(key.id); return n; });
      this.modelsError.update((s) => { const n = new Set(s); n.delete(key.id); return n; });
    } catch {
      this.modelsLoading.update((s) => { const n = new Set(s); n.delete(key.id); return n; });
      this.modelsError.update((s) => { const n = new Set(s); n.add(key.id); return n; });
    }
  }

  isExpanded(keyId: number): boolean { return this.expandedKeyIds().has(keyId); }
  isModelsLoading(keyId: number): boolean { return this.modelsLoading().has(keyId); }
  isModelsError(keyId: number): boolean { return this.modelsError().has(keyId); }
  getModels(keyId: number): ModelAccess[] { return this.keyModels().get(keyId) ?? []; }

  getModelGroups(keyId: number): ModelGroup[] {
    const groups = new Map<string, ModelGroup>();
    for (const m of this.getModels(keyId)) {
      const group = groups.get(m.model_name) ?? {
        model_name: m.model_name,
        providers: [],
        hasCloud: false,
        hasLocal: false,
      };
      if (!group.providers.includes(m.provider_name)) group.providers.push(m.provider_name);
      if (m.provider_type === 'cloud') group.hasCloud = true;
      else group.hasLocal = true;
      groups.set(m.model_name, group);
    }
    return [...groups.values()]
      .map((g) => ({ ...g, providers: g.providers.sort((a, b) => a.localeCompare(b)) }))
      // Cloud-bearing models first, then local-only; alphabetical within each group.
      .sort((a, b) => {
        if (a.hasCloud !== b.hasCloud) return a.hasCloud ? -1 : 1;
        return a.model_name.localeCompare(b.model_name);
      });
  }

  retryModels(key: MyKey): void {
    this.keyModels.update((m) => { const n = new Map(m); n.delete(key.id); return n; });
    this.expandedKeyIds.update((s) => { const n = new Set(s); n.delete(key.id); return n; });
    this.toggleModels(key);
  }

  // ── Logging toggle ─────────────────────────────────────────────────────────
  requestLogChange(key: MyKey, newLog: 'BILLING' | 'FULL'): void {
    if (key.log === newLog) return;
    this.logChangeError.set(false);
    this.logChangeTarget.set({ key, newLog });
  }

  closeLogModal(): void {
    if (this.logChangeLoading()) return;
    this.logChangeTarget.set(null);
  }

  async confirmLogChange(): Promise<void> {
    const target = this.logChangeTarget();
    if (!target || this.logChangeLoading()) return;
    this.logChangeLoading.set(true);
    this.logChangeError.set(false);
    try {
      await this.keysService.setLogLevel(target.key.id, target.newLog);
      this.workspaces.update((list) =>
        list.map((ws) => ({
          ...ws,
          keys: ws.keys.map((k) => (k.id === target.key.id ? { ...k, log: target.newLog } : k)),
        })),
      );
      this.logChangeTarget.set(null);
    } catch {
      this.logChangeError.set(true);
    } finally {
      this.logChangeLoading.set(false);
    }
  }

  logModalMessage(target: { key: MyKey; newLog: 'BILLING' | 'FULL' }): string {
    return target.newLog === 'FULL'
      ? `Switch "${target.key.name}" to Full logging? Full logging stores complete request and response content.`
      : `Switch "${target.key.name}" to Billing logging? Only metadata (no content) will be stored.`;
  }

  // ── Key budget ─────────────────────────────────────────────────────────────
  isKeyBudgetExhausted(key: MyKey): boolean {
    return (
      key.settings?.budget_limit_micro_cents != null &&
      key.used_micro_cents >= key.settings.budget_limit_micro_cents
    );
  }

  isTeamBudgetExhausted(team: MyTeam): boolean {
    return (
      team.team_monthly_budget_micro_cents != null &&
      team.budget_used_micro_cents >= team.team_monthly_budget_micro_cents
    );
  }

  budgetExhaustedMessage(team: MyTeam, key: MyKey): string | null {
    if (this.isTeamBudgetExhausted(team)) {
      return `Team budget exhausted — all ${team.name} keys are currently inactive.`;
    }
    if (this.isKeyBudgetExhausted(key)) {
      return 'Key budget exhausted — this key is currently inactive.';
    }
    return null;
  }

  keyBudgetPercent(key: MyKey): number {
    if (!key.settings?.budget_limit_micro_cents) return 0;
    return Math.min(100, (key.used_micro_cents / key.settings.budget_limit_micro_cents) * 100);
  }

  // ── Display ────────────────────────────────────────────────────────────────
  formatRpm(rpm: number | null): string {
    return rpm != null ? rpm.toLocaleString() : '∞';
  }

  formatTpm(tpm: number | null): string {
    if (tpm == null) return '∞';
    return tpm >= 1000 ? (tpm / 1000).toFixed(0) + 'k' : tpm.toString();
  }

  formatLastUsed(iso: string | null): string {
    if (!iso) return 'Never';
    const d = new Date(iso);
    const today = new Date();
    const diffDays = Math.floor((today.getTime() - d.getTime()) / 86_400_000);
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    return d.toLocaleDateString();
  }
}
