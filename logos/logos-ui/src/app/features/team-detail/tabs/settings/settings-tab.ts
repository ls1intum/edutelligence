import { Component, Input, Output, EventEmitter, signal, inject, OnChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { TeamDetail, TeamLimitsPayload } from '../../../../shared/models/team.model';
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

function strToIntOrNull(s: string): number | null {
  const v = parseInt(s.trim(), 10);
  return isNaN(v) ? null : v;
}

@Component({
  selector: 'app-settings-tab',
  standalone: true,
  imports: [FormsModule, ModalConfirmComponent, ErrorMessageComponent],
  templateUrl: './settings-tab.html',
  styleUrl: './settings-tab.scss',
})
export class SettingsTabComponent implements OnChanges {
  @Input() team!: TeamDetail;
  @Input() teamId!: number;
  @Input() canEdit = false;
  @Output() refresh     = new EventEmitter<void>();
  @Output() teamDeleted = new EventEmitter<void>();

  private teamService = inject(TeamManagementService);

  defaultBudget = signal('');
  cloudRpm      = signal('');
  cloudTpm      = signal('');
  localRpm      = signal('');
  localTpm      = signal('');

  saveLoading = signal(false);
  saveError   = signal('');
  saveSuccess = signal(false);

  deleteOpen    = signal(false);
  deleteLoading = signal(false);
  deleteError   = signal(false);

  ngOnChanges(): void {
    if (this.team) this.resetForm();
  }

  private resetForm(): void {
    this.defaultBudget.set(mcToDollars(this.team.default_monthly_budget_micro_cents));
    this.cloudRpm.set(this.team.default_cloud_rpm_limit?.toString() ?? '');
    this.cloudTpm.set(this.team.default_cloud_tpm_limit?.toString() ?? '');
    this.localRpm.set(this.team.default_local_rpm_limit?.toString() ?? '');
    this.localTpm.set(this.team.default_local_tpm_limit?.toString() ?? '');
  }

  saveSettings(): void {
    if (this.saveLoading()) return;
    this.saveLoading.set(true);
    this.saveError.set('');
    this.saveSuccess.set(false);

    const payload: TeamLimitsPayload = {
      default_monthly_budget_micro_cents: dollarsToMc(this.defaultBudget()),
      default_cloud_rpm_limit: strToIntOrNull(this.cloudRpm()),
      default_cloud_tpm_limit: strToIntOrNull(this.cloudTpm()),
      default_local_rpm_limit: strToIntOrNull(this.localRpm()),
      default_local_tpm_limit: strToIntOrNull(this.localTpm()),
    };

    this.teamService.updateTeamLimits(this.teamId, payload).subscribe({
      next: () => {
        this.saveLoading.set(false);
        this.saveSuccess.set(true);
        this.refresh.emit();
        setTimeout(() => this.saveSuccess.set(false), 3000);
      },
      error: () => {
        this.saveLoading.set(false);
        this.saveError.set('Failed to save settings, please try again.');
      },
    });
  }

  confirmDelete(): void {
    if (this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    this.teamService.deleteTeam(this.teamId).subscribe({
      next: () => {
        this.deleteLoading.set(false);
        this.deleteOpen.set(false);
        this.teamDeleted.emit();
      },
      error: () => {
        this.deleteLoading.set(false);
        this.deleteError.set(true);
      },
    });
  }
}
