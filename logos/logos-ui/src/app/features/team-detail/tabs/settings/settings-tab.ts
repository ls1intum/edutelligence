import {
  Component,
  Input,
  Output,
  EventEmitter,
  signal,
  inject,
  OnChanges,
  SimpleChanges,
  ChangeDetectionStrategy,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import {
  ProviderItem,
  TeamDetail,
  TeamLimitsPayload,
  TeamProviderBudget,
} from '../../../../shared/models/team.model';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';

const MICRO = 100_000_000;

function mcToDollars(mc: number | null): string {
  if (mc == null) return '';
  return (mc / MICRO).toString();
}

function dollarsToMc(s: string): number | null {
  const v = parseFloat(s.trim().replace(',', '.'));
  return isNaN(v) ? null : Math.round(v * MICRO);
}

/**
 * A provider cap as typed: blank is no cap (null), a non-negative dollar
 * amount is a cap, and anything else is rejected (undefined) rather than read
 * as "no cap".
 */
export function parseProviderCap(s: string): number | null | undefined {
  const trimmed = s.trim();
  if (trimmed === '') return null;
  if (!/^\d+([.,]\d+)?$/.test(trimmed)) return undefined;
  const mc = Math.round(Number(trimmed.replace(',', '.')) * MICRO);
  return Number.isSafeInteger(mc) ? mc : undefined;
}

function strToIntOrNull(s: string): number | null {
  const v = parseInt(s.trim(), 10);
  return isNaN(v) ? null : v;
}

@Component({
  selector: 'app-settings-tab',
  standalone: true,
  imports: [FormsModule, ModalConfirmComponent, ErrorMessageComponent],
  templateUrl: './settings-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './settings-tab.scss',
})
export class SettingsTabComponent implements OnChanges {
  @Input() team!: TeamDetail;
  @Input() teamId!: number;
  @Input() canEdit = false;
  @Output() refresh = new EventEmitter<void>();
  @Output() teamDeleted = new EventEmitter<void>();

  private teamService = inject(TeamManagementService);

  teamBudget = signal('');
  defaultBudget = signal('');
  cloudRpm = signal('');
  cloudTpm = signal('');
  localRpm = signal('');
  localTpm = signal('');

  providerBudgets = signal<TeamProviderBudget[]>([]);
  cloudProviders = signal<ProviderItem[]>([]);
  newProviderId = signal('');
  newProviderBudget = signal('');
  providerBudgetLoading = signal(false);
  providerBudgetError = signal('');

  saveLoading = signal(false);
  saveError = signal('');
  saveSuccess = signal(false);

  deleteOpen = signal(false);
  deleteLoading = signal(false);
  deleteError = signal(false);

  ngOnChanges(changes: SimpleChanges): void {
    if (this.team) this.resetForm();
    if (this.teamId && changes['teamId']) void this.loadProviderBudgets();
  }

  private resetForm(): void {
    this.teamBudget.set(mcToDollars(this.team.team_monthly_budget_micro_cents));
    this.defaultBudget.set(mcToDollars(this.team.default_monthly_budget_micro_cents));
    this.cloudRpm.set(this.team.default_cloud_rpm_limit?.toString() ?? '');
    this.cloudTpm.set(this.team.default_cloud_tpm_limit?.toString() ?? '');
    this.localRpm.set(this.team.default_local_rpm_limit?.toString() ?? '');
    this.localTpm.set(this.team.default_local_tpm_limit?.toString() ?? '');
  }

  private async loadProviderBudgets(): Promise<void> {
    this.providerBudgetError.set('');
    try {
      const [budgets, providers] = await Promise.all([
        this.teamService.getTeamProviderBudgets(this.teamId),
        this.teamService.getAllProviders(),
      ]);
      this.providerBudgets.set(budgets);
      this.cloudProviders.set(providers.filter((p) => p.provider_type === 'cloud'));
    } catch {
      this.providerBudgetError.set('Failed to load sponsored provider budgets.');
    }
  }

  availableCloudProviders(): ProviderItem[] {
    const taken = new Set(this.providerBudgets().map((b) => b.provider_id));
    return this.cloudProviders().filter((p) => !taken.has(p.id));
  }

  budgetLabel(mc: number | null): string {
    return mc == null ? 'Unlimited' : `$${mcToDollars(mc)}`;
  }

  async addProviderBudget(): Promise<void> {
    if (this.providerBudgetLoading() || !this.canEdit) return;
    const providerId = parseInt(this.newProviderId(), 10);
    if (isNaN(providerId)) {
      this.providerBudgetError.set('Select a cloud provider.');
      return;
    }
    const cap = parseProviderCap(this.newProviderBudget());
    if (cap === undefined) {
      this.providerBudgetError.set(
        'Enter a dollar amount such as 50 or 12.50, or leave it blank for unlimited.',
      );
      return;
    }
    this.providerBudgetLoading.set(true);
    this.providerBudgetError.set('');
    try {
      await this.teamService.upsertTeamProviderBudget(this.teamId, providerId, cap);
      this.newProviderId.set('');
      this.newProviderBudget.set('');
      await this.loadProviderBudgets();
    } catch {
      this.providerBudgetError.set('Failed to save provider budget.');
    } finally {
      this.providerBudgetLoading.set(false);
    }
  }

  async removeProviderBudget(providerId: number): Promise<void> {
    if (this.providerBudgetLoading() || !this.canEdit) return;
    this.providerBudgetLoading.set(true);
    this.providerBudgetError.set('');
    try {
      await this.teamService.deleteTeamProviderBudget(this.teamId, providerId);
      await this.loadProviderBudgets();
    } catch {
      this.providerBudgetError.set('Failed to remove provider budget.');
    } finally {
      this.providerBudgetLoading.set(false);
    }
  }

  async saveSettings(): Promise<void> {
    if (this.saveLoading()) return;
    this.saveLoading.set(true);
    this.saveError.set('');
    this.saveSuccess.set(false);

    const payload: TeamLimitsPayload = {
      team_monthly_budget_micro_cents: dollarsToMc(this.teamBudget()),
      default_monthly_budget_micro_cents: dollarsToMc(this.defaultBudget()),
      default_cloud_rpm_limit: strToIntOrNull(this.cloudRpm()),
      default_cloud_tpm_limit: strToIntOrNull(this.cloudTpm()),
      default_local_rpm_limit: strToIntOrNull(this.localRpm()),
      default_local_tpm_limit: strToIntOrNull(this.localTpm()),
    };

    try {
      await this.teamService.updateTeamLimits(this.teamId, payload);
      this.saveSuccess.set(true);
      this.refresh.emit();
      setTimeout(() => this.saveSuccess.set(false), 3000);
    } catch {
      this.saveError.set('Failed to save settings, please try again.');
    } finally {
      this.saveLoading.set(false);
    }
  }

  async confirmDelete(): Promise<void> {
    if (this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    try {
      await this.teamService.deleteTeam(this.teamId);
      this.deleteOpen.set(false);
      this.teamDeleted.emit();
    } catch {
      this.deleteError.set(true);
    } finally {
      this.deleteLoading.set(false);
    }
  }
}
