import {
  Component,
  computed,
  inject,
  signal,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgClass } from '@angular/common';
import { ModalFormComponent } from '../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';
import { AuthService } from '../../core/auth/services/auth.service';
import { PolicyService } from '../../core/services/policy.service';
import { TeamManagementService } from '../../core/services/team-management.service';
import { Policy, ThresholdLevel, AddPolicyPayload } from '../../shared/models/policy.model';
import { SearchInputComponent } from '../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';

interface TeamOption {
  id: number;
  name: string;
}
interface ApiKeyOption {
  id: number;
  name: string;
  teamName: string;
}

@Component({
  selector: 'app-policies',
  standalone: true,
  imports: [
    FormsModule,
    NgClass,
    ModalFormComponent,
    ModalConfirmComponent,
    SearchInputComponent,
    DataTableComponent,
    ErrorMessageComponent,
  ],
  templateUrl: './policies.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './policies.scss',
})
export class Policies implements OnInit {
  private auth = inject(AuthService);
  private policyService = inject(PolicyService);
  private teamService = inject(TeamManagementService);

  // ── List state ───────────────────────────────────────────────────────────
  policies = signal<Policy[]>([]);
  loading = signal(true);
  loadError = signal(false);
  search = signal('');
  expandedIds = signal<Set<number>>(new Set());

  // ── Delete modal ─────────────────────────────────────────────────────────
  deleteTarget = signal<Policy | null>(null);
  deleteLoading = signal(false);
  deleteError = signal(false);

  // ── Add / Edit modal ─────────────────────────────────────────────────────
  formOpen = signal(false);
  formMode = signal<'add' | 'edit'>('add');
  formLoading = signal(false);
  formError = signal('');
  editTarget = signal<Policy | null>(null);

  // Dropdown options
  availableTeams = signal<TeamOption[]>([]);
  availableApiKeys = signal<ApiKeyOption[]>([]);
  dropdownLoading = signal(false);

  // Form fields
  formName = signal('');
  formDescription = signal('');
  formPrivacy = signal<ThresholdLevel>('LOCAL');
  formLatency = signal(0);
  formAccuracy = signal(0);
  formCost = signal(0);
  formQuality = signal(0);
  formPriority = signal(1);
  formTopic = signal('');
  formApiKeyId = signal<number | null>(null);
  formTeamId = signal<number | null>(null);

  // ── Computed ──────────────────────────────────────────────────────────────
  filteredPolicies = computed(() => {
    const q = this.search().toLowerCase().trim();
    if (!q) return this.policies();
    return this.policies().filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.description ?? '').toLowerCase().includes(q) ||
        (p.topic ?? '').toLowerCase().includes(q),
    );
  });

  formValid = computed(() => this.formName().trim().length > 0);

  ngOnInit(): void {
    this.fetchPolicies();
  }

  // ── Data fetching ─────────────────────────────────────────────────────────
  async fetchPolicies(): Promise<void> {
    this.loading.set(true);
    this.loadError.set(false);
    try {
      const list = await this.policyService.getPolicies();
      this.policies.set(list);
    } catch {
      this.loadError.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  private async loadDropdownData(): Promise<void> {
    if (this.availableTeams().length > 0) return;
    this.dropdownLoading.set(true);
    try {
      const teams = await this.teamService.getTeams();
      this.availableTeams.set(teams.map((t) => ({ id: t.id, name: t.name })));
      if (teams.length > 0) {
        const results = await Promise.all(teams.map((t) => this.teamService.getTeamApiKeys(t.id)));
        const keys: ApiKeyOption[] = results.flatMap((keys, i) =>
          keys.map((k) => ({ id: k.id, name: k.name, teamName: teams[i].name })),
        );
        this.availableApiKeys.set(keys);
      }
    } catch {
      // leave dropdownLoading false below
    } finally {
      this.dropdownLoading.set(false);
    }
  }

  // ── Row expansion ─────────────────────────────────────────────────────────
  toggleExpand(id: number): void {
    const s = new Set(this.expandedIds());
    if (s.has(id)) {
      s.delete(id);
    } else {
      s.add(id);
    }
    this.expandedIds.set(s);
  }

  isExpanded(id: number): boolean {
    return this.expandedIds().has(id);
  }

  // ── Display helpers ───────────────────────────────────────────────────────
  ownerLabel(policy: Policy): string {
    if (policy.team_id !== null) {
      const team = this.availableTeams().find((t) => t.id === policy.team_id);
      return team ? team.name : `Team #${policy.team_id}`;
    }
    if (policy.api_key_id !== null) {
      const key = this.availableApiKeys().find((k) => k.id === policy.api_key_id);
      return key ? `${key.name} (${key.teamName})` : `Key #${policy.api_key_id}`;
    }
    return '-';
  }

  privacyLabel(level: string): string {
    const labels: Record<string, string> = {
      LOCAL: 'Local',
      CLOUD_IN_EU_BY_EU_PROVIDER: 'EU / EU',
      CLOUD_IN_EU_BY_US_PROVIDER: 'EU / US',
      CLOUD_NOT_IN_EU_BY_US_PROVIDER: 'Non-EU / US',
    };
    return labels[level] ?? level;
  }

  privacyClass(level: string): string {
    const classes: Record<string, string> = {
      LOCAL: 'local',
      CLOUD_IN_EU_BY_EU_PROVIDER: 'eu-eu',
      CLOUD_IN_EU_BY_US_PROVIDER: 'eu-us',
      CLOUD_NOT_IN_EU_BY_US_PROVIDER: 'non-eu',
    };
    return classes[level] ?? 'local';
  }

  // ── Delete flow ───────────────────────────────────────────────────────────
  openDeleteDialog(policy: Policy): void {
    this.deleteTarget.set(policy);
    this.deleteError.set(false);
  }

  closeDeleteDialog(): void {
    if (this.deleteLoading()) return;
    this.deleteTarget.set(null);
    this.deleteError.set(false);
  }

  async confirmDelete(): Promise<void> {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    try {
      await this.policyService.deletePolicy(target.id);
      this.policies.update((list) => list.filter((p) => p.id !== target.id));
      this.deleteTarget.set(null);
    } catch {
      this.deleteError.set(true);
    } finally {
      this.deleteLoading.set(false);
    }
  }

  // ── Form helpers ──────────────────────────────────────────────────────────
  private resetForm(): void {
    this.formName.set('');
    this.formDescription.set('');
    this.formPrivacy.set('LOCAL');
    this.formLatency.set(0);
    this.formAccuracy.set(0);
    this.formCost.set(0);
    this.formQuality.set(0);
    this.formPriority.set(1);
    this.formTopic.set('');
    this.formApiKeyId.set(null);
    this.formTeamId.set(null);
    this.formError.set('');
  }

  // ── Add / Edit flow ───────────────────────────────────────────────────────
  openAddDialog(): void {
    this.formMode.set('add');
    this.editTarget.set(null);
    this.resetForm();
    this.loadDropdownData();
    this.formOpen.set(true);
  }

  openEditDialog(policy: Policy): void {
    this.formMode.set('edit');
    this.editTarget.set(policy);
    this.formName.set(policy.name);
    this.formDescription.set(policy.description ?? '');
    this.formPrivacy.set(policy.threshold_privacy as ThresholdLevel);
    this.formLatency.set(policy.threshold_latency);
    this.formAccuracy.set(policy.threshold_accuracy);
    this.formCost.set(policy.threshold_cost);
    this.formQuality.set(policy.threshold_quality);
    this.formPriority.set(policy.priority);
    this.formTopic.set(policy.topic ?? '');
    this.formApiKeyId.set(policy.api_key_id);
    this.formTeamId.set(policy.team_id);
    this.formError.set('');
    this.loadDropdownData();
    this.formOpen.set(true);
  }

  closeFormDialog(): void {
    if (this.formLoading()) return;
    this.formOpen.set(false);
  }

  async submitForm(): Promise<void> {
    if (!this.formValid() || this.formLoading()) return;
    this.formLoading.set(true);
    this.formError.set('');

    const payload: AddPolicyPayload = {
      name: this.formName().trim(),
      description: this.formDescription().trim(),
      threshold_privacy: this.formPrivacy(),
      threshold_latency: this.formLatency(),
      threshold_accuracy: this.formAccuracy(),
      threshold_cost: this.formCost(),
      threshold_quality: this.formQuality(),
      priority: this.formPriority(),
      topic: this.formTopic().trim() || null,
      api_key_id: this.formApiKeyId(),
      team_id: this.formTeamId(),
    };

    try {
      if (this.formMode() === 'add') {
        await this.policyService.addPolicy(payload);
      } else {
        const target = this.editTarget();
        if (!target) return;
        await this.policyService.updatePolicy({ id: target.id, ...payload });
      }
      await this.fetchPolicies();
      this.formOpen.set(false);
    } catch {
      if (this.formMode() === 'add') {
        this.formError.set('Failed to create policy, please try again.');
      } else {
        this.formError.set('Failed to update policy, please try again.');
      }
    } finally {
      this.formLoading.set(false);
    }
  }
}
