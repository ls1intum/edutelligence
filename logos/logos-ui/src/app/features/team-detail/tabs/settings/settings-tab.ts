import {
  Component,
  Input,
  Output,
  EventEmitter,
  signal,
  inject,
  OnChanges,
  ChangeDetectionStrategy,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import {
  KeycloakGroupOption,
  TeamDetail,
  TeamLimitsPayload,
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

  /** Nothing to save while the field still shows what the team is linked to. */
  linkChanged(): boolean {
    return this.keycloakGroup().trim() !== (this.team?.keycloak_group ?? '');
  }

  ngOnChanges(): void {
    if (this.team) this.resetForm();
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
  }

  /** Group suggestions for the link field; silently stays free text on failure. */
  private async fetchKeycloakGroups(): Promise<void> {
    try {
      const directory = await this.teamService.getKeycloakGroups();
      this.keycloakGroupOptions.set(directory.available ? directory.groups : []);
    } catch {
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
