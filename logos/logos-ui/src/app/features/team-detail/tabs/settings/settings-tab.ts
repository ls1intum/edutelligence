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
  KeycloakGroupOption,
  ProviderItem,
  TeamDetail,
  TeamLimitsPayload,
  TeamProviderBudget,
} from '../../../../shared/models/team.model';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';
import { errorDetail } from '../../../../shared/utils/error-detail';

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
  /** Logos admins only: the Keycloak link decides who ends up in the team. */
  @Input() canLinkKeycloak = false;
  @Output() refresh = new EventEmitter<void>();
  @Output() teamDeleted = new EventEmitter<void>();

  private teamService = inject(TeamManagementService);

  teamBudget = signal('');
  defaultBudget = signal('');
  cloudRpm = signal('');
  cloudTpm = signal('');
  localRpm = signal('');
  localTpm = signal('');
  showOnPublicStats = signal(false);
  publicCategory = signal('');
  /** Categories other teams already use, so the same label is spelled the same way. */
  publicCategoryOptions = signal<string[]>([]);
  private publicCategoriesRequested = false;

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

  // ── Keycloak link ─────────────────────────────────────────────────────────
  keycloakGroup = signal('');
  /** Realm groups and roles to suggest; empty when the deployment has no
   *  Keycloak directory access, in which case the field stays free text. */
  keycloakGroupOptions = signal<KeycloakGroupOption[]>([]);
  /** The deployment can read the realm; false means the field is free text only. */
  keycloakDirectoryAvailable = signal(false);
  /** The directory was asked once; it stays the same while the tab is open. */
  private keycloakGroupsRequested = false;
  linkLoading = signal(false);
  linkError = signal('');
  linkSuccess = signal(false);

  /** Suggestions minus the groups another team already holds — the link is unique. */
  availableKeycloakGroups(): KeycloakGroupOption[] {
    return this.keycloakGroupOptions()
      .filter((g) => g.linked_team_id === null || g.linked_team_id === this.teamId);
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
    return `Pick one of the ${free} selectable groups and roles in the realm, or type another.`;
  }

  /** Nothing to save while the field still shows what the team is linked to. */
  linkChanged(): boolean {
    return this.keycloakGroup().trim() !== (this.team?.keycloak_group ?? '');
  }

  /** Clearing the field only removes something when a link is actually stored. */
  linkButtonLabel(): string {
    return !this.keycloakGroup().trim() && this.team?.keycloak_group ? 'Remove Link' : 'Save Link';
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (this.team) this.resetForm();
    if (this.teamId && changes['teamId']) void this.loadProviderBudgets();
    if (this.canEdit && !this.publicCategoriesRequested) {
      this.publicCategoriesRequested = true;
      void this.fetchPublicCategories();
    }
    if (this.canLinkKeycloak && !this.keycloakGroupsRequested) {
      this.keycloakGroupsRequested = true;
      void this.fetchKeycloakGroups();
    }
  }

  private resetForm(): void {
    this.teamBudget.set(mcToDollars(this.team.team_monthly_budget_micro_cents));
    this.defaultBudget.set(mcToDollars(this.team.default_monthly_budget_micro_cents));
    this.cloudRpm.set(this.team.default_cloud_rpm_limit?.toString() ?? '');
    this.cloudTpm.set(this.team.default_cloud_tpm_limit?.toString() ?? '');
    this.localRpm.set(this.team.default_local_rpm_limit?.toString() ?? '');
    this.localTpm.set(this.team.default_local_tpm_limit?.toString() ?? '');
    this.keycloakGroup.set(this.team.keycloak_group ?? '');
    this.showOnPublicStats.set(!!this.team.show_on_public_stats);
    this.publicCategory.set(this.team.public_category ?? '');
  }

  /** Category suggestions; the field stays free text when they cannot be loaded. */
  private async fetchPublicCategories(): Promise<void> {
    try {
      this.publicCategoryOptions.set(await this.teamService.getPublicCategories());
    } catch {
      this.publicCategoryOptions.set([]);
    }
  }

  /** Group suggestions for the link field; silently stays free text on failure. */
  private async fetchKeycloakGroups(): Promise<void> {
    try {
      const directory = await this.teamService.getKeycloakGroups();
      this.keycloakDirectoryAvailable.set(directory.available);
      this.keycloakGroupOptions.set(directory.available ? directory.groups : []);
    } catch {
      this.keycloakDirectoryAvailable.set(false);
      this.keycloakGroupOptions.set([]);
    }
  }

  /**
   * Saves the Keycloak link; a blank field removes it. Removing or repointing
   * it also drops the memberships the old group produced, so the whole team has
   * to be reloaded afterwards.
   */
  async saveKeycloakLink(): Promise<void> {
    if (this.linkLoading() || !this.linkChanged()) return;
    this.linkLoading.set(true);
    this.linkError.set('');
    this.linkSuccess.set(false);
    const group = this.keycloakGroup().trim();
    try {
      await this.teamService.updateTeamKeycloakGroup(this.teamId, group || null);
      this.linkSuccess.set(true);
      this.refresh.emit();
      setTimeout(() => this.linkSuccess.set(false), 3000);
    } catch (err) {
      this.linkError.set(errorDetail(err) ?? 'Failed to save the Keycloak link, please try again.');
    } finally {
      this.linkLoading.set(false);
    }
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
      show_on_public_stats: this.showOnPublicStats(),
      public_category: this.publicCategory().trim(),
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
