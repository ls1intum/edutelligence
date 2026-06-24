import { Component, Input, OnInit, signal, inject, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ModalFormComponent } from '../../../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import { SearchInputComponent } from '../../../../shared/components/search-input/search-input';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';

interface ModelRow {
  id: number;
  model_name: string;
  provider_names: string[];
}

@Component({
  selector: 'app-models-tab',
  standalone: true,
  imports: [
    FormsModule,
    ModalFormComponent,
    ModalConfirmComponent,
    DataTableComponent,
    SearchInputComponent,
    ErrorMessageComponent,
  ],
  templateUrl: './models-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './models-tab.scss',
})
export class ModelsTabComponent implements OnInit {
  @Input() teamId!: number;
  @Input() canEdit = false;

  private teamService = inject(TeamManagementService);

  // All models reachable via team's assigned providers: model_id → row
  private modelMap = new Map<number, ModelRow>();

  assignedIds = signal<Set<number>>(new Set());
  loading = signal(true);
  error = signal(false);

  get assigned(): ModelRow[] {
    const ids = this.assignedIds();
    return [...this.modelMap.values()].filter((m) => ids.has(m.id));
  }

  get available(): ModelRow[] {
    const ids = this.assignedIds();
    return [...this.modelMap.values()].filter((m) => !ids.has(m.id));
  }

  // ── Add dialog ─────────────────────────────────────────────────────────────
  addOpen = signal(false);
  search = signal('');
  stagedIds = signal<Set<number>>(new Set());
  saving = signal(false);
  saveError = signal('');

  get filteredAvailable(): ModelRow[] {
    const q = this.search().toLowerCase().trim();
    if (!q) return this.available;
    return this.available.filter(
      (m) =>
        m.model_name.toLowerCase().includes(q) ||
        m.provider_names.some((p) => p.toLowerCase().includes(q)),
    );
  }

  get stagedCount(): number {
    return this.stagedIds().size;
  }

  isStaged(id: number): boolean {
    return this.stagedIds().has(id);
  }

  toggleStage(id: number): void {
    const next = new Set(this.stagedIds());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.stagedIds.set(next);
  }

  openAddDialog(): void {
    this.search.set('');
    this.stagedIds.set(new Set());
    this.saveError.set('');
    this.addOpen.set(true);
  }

  async confirmAdd(): Promise<void> {
    if (this.stagedCount === 0 || this.saving()) return;
    const newIds = [...this.assignedIds(), ...this.stagedIds()];
    this.saving.set(true);
    this.saveError.set('');
    try {
      await this.teamService.setTeamModelPermissions(this.teamId, newIds);
      this.assignedIds.set(new Set(newIds));
      this.addOpen.set(false);
    } catch {
      this.saveError.set('Failed to update models, please try again.');
    } finally {
      this.saving.set(false);
    }
  }

  // ── Remove confirm dialog ──────────────────────────────────────────────────
  confirmOpen = signal(false);
  pendingRemove = signal<ModelRow | null>(null);
  removing = signal(false);
  removeError = signal('');

  promptRemove(m: ModelRow): void {
    this.pendingRemove.set(m);
    this.removeError.set('');
    this.confirmOpen.set(true);
  }

  async executeRemove(): Promise<void> {
    const target = this.pendingRemove();
    if (!target || this.removing()) return;
    const newIds = [...this.assignedIds()].filter((id) => id !== target.id);
    this.removing.set(true);
    this.removeError.set('');
    try {
      await this.teamService.setTeamModelPermissions(this.teamId, newIds);
      this.assignedIds.set(new Set(newIds));
      this.confirmOpen.set(false);
      this.pendingRemove.set(null);
    } catch {
      this.removeError.set('Failed to remove model, please try again.');
    } finally {
      this.removing.set(false);
    }
  }

  async ngOnInit(): Promise<void> {
    try {
      const [modelIds, providerIds, providers] = await Promise.all([
        this.teamService.getTeamModelPermissions(this.teamId),
        this.teamService.getTeamProviderPermissions(this.teamId),
        this.teamService.getAllProviders(),
      ]);

      const providerIdSet = new Set(providerIds);
      const teamProviders = providers.filter((p) => providerIdSet.has(p.id));

      await Promise.all(
        teamProviders.map(async (p) => {
          try {
            const models = await this.teamService.getProviderModels(p.id);
            for (const m of models ?? []) {
              const existing = this.modelMap.get(m.model_id);
              if (existing) {
                existing.provider_names.push(p.name);
              } else {
                this.modelMap.set(m.model_id, {
                  id: m.model_id,
                  model_name: m.model_name,
                  provider_names: [p.name],
                });
              }
            }
          } catch {
            /* skip unreachable provider */
          }
        }),
      );

      this.assignedIds.set(new Set(modelIds));
    } catch {
      this.error.set(true);
    } finally {
      this.loading.set(false);
    }
  }
}
