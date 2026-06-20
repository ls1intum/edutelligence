import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Dialog } from 'primeng/dialog';
import { MyKeysService } from './my-keys.service';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';

@Component({
  selector: 'app-my-keys',
  standalone: true,
  imports: [CommonModule, Dialog, ErrorMessageComponent],
  templateUrl: './my-keys.html',
  styleUrl: './my-keys.scss',
})
export class MyKeys implements OnInit {
  private service = inject(MyKeysService);

  keys           = signal<MyKey[]>([]);
  loading        = signal(true);
  loadError      = signal(false);

  expandedKeyIds = signal<Set<number>>(new Set());
  keyModels      = signal<Map<number, ModelAccess[]>>(new Map());
  modelsLoading  = signal<Set<number>>(new Set());
  modelsError    = signal<Set<number>>(new Set());

  logChangeTarget  = signal<{ key: MyKey; newLog: 'BILLING' | 'FULL' } | null>(null);
  logChangeLoading = signal(false);
  logChangeError   = signal(false);

  copiedKeyId = signal<number | null>(null);

  ngOnInit(): void {
    this.loadKeys();
  }

  loadKeys(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.service.getMyKeys().subscribe({
      next: keys => { this.keys.set(keys); this.loading.set(false); },
      error: ()   => { this.loadError.set(true); this.loading.set(false); },
    });
  }

  // ── Key masking ───────────────────────────────────────────────────────────
  maskedKey(keyValue: string): string {
    const prefix = keyValue.slice(0, 14);
    return `${prefix} · · · · · · · · ·`;
  }

  // ── Copy ──────────────────────────────────────────────────────────────────
  copyKey(key: MyKey): void {
    navigator.clipboard.writeText(key.key_value).then(() => {
      this.copiedKeyId.set(key.id);
      setTimeout(() => this.copiedKeyId.set(null), 2000);
    });
  }

  isCopied(keyId: number): boolean {
    return this.copiedKeyId() === keyId;
  }

  // ── Expand models ─────────────────────────────────────────────────────────
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

    const loading = new Set(this.modelsLoading());
    loading.add(key.id);
    this.modelsLoading.set(loading);

    this.service.getKeyModels(key.id).subscribe({
      next: models => {
        this.keyModels.update(m => { const n = new Map(m); n.set(key.id, models); return n; });
        this.modelsLoading.update(s => { const n = new Set(s); n.delete(key.id); return n; });
        this.modelsError.update(s => { const n = new Set(s); n.delete(key.id); return n; });
      },
      error: () => {
        this.modelsLoading.update(s => { const n = new Set(s); n.delete(key.id); return n; });
        this.modelsError.update(s => { const n = new Set(s); n.add(key.id); return n; });
      },
    });
  }

  isExpanded(keyId: number): boolean { return this.expandedKeyIds().has(keyId); }
  isModelsLoading(keyId: number): boolean { return this.modelsLoading().has(keyId); }
  isModelsError(keyId: number): boolean { return this.modelsError().has(keyId); }
  getModels(keyId: number): ModelAccess[] { return this.keyModels().get(keyId) ?? []; }

  retryModels(key: MyKey): void {
    this.keyModels.update(m => { const n = new Map(m); n.delete(key.id); return n; });
    this.expandedKeyIds.update(s => { const n = new Set(s); n.delete(key.id); return n; });
    this.toggleModels(key);
  }

  // ── Logging toggle ────────────────────────────────────────────────────────
  requestLogChange(key: MyKey, newLog: 'BILLING' | 'FULL'): void {
    if (key.log === newLog) return;
    this.logChangeError.set(false);
    this.logChangeTarget.set({ key, newLog });
  }

  closeLogModal(): void {
    if (this.logChangeLoading()) return;
    this.logChangeTarget.set(null);
  }

  confirmLogChange(): void {
    const target = this.logChangeTarget();
    if (!target || this.logChangeLoading()) return;
    this.logChangeLoading.set(true);
    this.logChangeError.set(false);
    this.service.setLogLevel(target.key.id, target.newLog).subscribe({
      next: () => {
        this.keys.update(list =>
          list.map(k => k.id === target.key.id ? { ...k, log: target.newLog } : k)
        );
        this.logChangeLoading.set(false);
        this.logChangeTarget.set(null);
      },
      error: () => {
        this.logChangeLoading.set(false);
        this.logChangeError.set(true);
      },
    });
  }

  logModalMessage(target: { key: MyKey; newLog: 'BILLING' | 'FULL' }): string {
    return target.newLog === 'FULL'
      ? `Switch "${target.key.name}" to Full logging? Full logging stores complete request and response content.`
      : `Switch "${target.key.name}" to Billing logging? Only metadata (no content) will be stored.`;
  }

  // ── Budget helpers ────────────────────────────────────────────────────────
  isKeyBudgetExhausted(key: MyKey): boolean {
    return key.settings.budget_limit_micro_cents != null
      && key.used_micro_cents >= key.settings.budget_limit_micro_cents;
  }

  isTeamBudgetExhausted(key: MyKey): boolean {
    return key.team.team_monthly_budget_micro_cents != null
      && key.team.budget_used_micro_cents >= key.team.team_monthly_budget_micro_cents;
  }

  budgetExhaustedMessage(key: MyKey): string | null {
    if (this.isTeamBudgetExhausted(key)) {
      return `Team budget exhausted — all ${key.team.name} keys are currently inactive.`;
    }
    if (this.isKeyBudgetExhausted(key)) {
      return 'Key budget exhausted — this key is currently inactive.';
    }
    return null;
  }

  budgetPercent(key: MyKey): number {
    if (!key.settings.budget_limit_micro_cents) return 0;
    return Math.min(100, (key.used_micro_cents / key.settings.budget_limit_micro_cents) * 100);
  }

  // ── Display helpers ───────────────────────────────────────────────────────
  formatMicroCents(mc: number | null): string {
    if (mc == null) return '∞';
    return '$' + (mc / 1_000_000).toFixed(2);
  }

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

  avatarLetter(name: string): string {
    return (name.charAt(0) || '?').toUpperCase();
  }

  providerTypeLabel(type: string): string {
    return type === 'LOCAL' ? 'Local' : 'Cloud';
  }
}
