import {
  Component,
  computed,
  inject,
  signal,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ModalFormComponent } from '../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';
import {
  ModelManagementService,
  ModelCapability,
  ModelCapabilityState,
} from '../../core/services/model-management.service';
import { Model, AddModelPayload, UpdateModelPayload } from '../../shared/models/model.model';
import { SearchInputComponent } from '../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { AuthService } from '../../core/auth/services/auth.service';
import { Router } from '@angular/router';
import { daysSince, formatLastUsed as formatLastUsedLabel } from '../../shared/utils/date';

@Component({
  selector: 'app-models',
  standalone: true,
  imports: [
    FormsModule,
    ModalFormComponent,
    ModalConfirmComponent,
    SearchInputComponent,
    DataTableComponent,
    ErrorMessageComponent,
  ],
  templateUrl: './models.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './models.scss',
})
export class Models implements OnInit {
  private modelService = inject(ModelManagementService);
  readonly role = inject(AuthService).role;
  private router = inject(Router);

  /**
   * A model without a single logged request for this long is highlighted as a
   * deprecation candidate.
   */
  private static readonly STALE_AFTER_DAYS = 30;

  // ── List state ──────────────────────────────────────────────────────────
  models = signal<Model[]>([]);
  capabilities = signal<Record<number, ModelCapability>>({});
  loading = signal(true);
  search = signal('');
  loadError = signal(false);
  /** Sort of the last-used column: unsorted, oldest first or newest first. */
  lastUsedSort = signal<'none' | 'asc' | 'desc'>('none');

  /** Sort direction for the table header; null while unsorted. */
  get lastUsedSortDirection(): 'asc' | 'desc' | null {
    const dir = this.lastUsedSort();
    return dir === 'asc' || dir === 'desc' ? dir : null;
  }

  // ── Delete modal ────────────────────────────────────────────────────────
  deleteTarget = signal<Model | null>(null);
  deleteLoading = signal(false);
  deleteError = signal(false);

  // ── Add modal ────────────────────────────────────────────────────────────
  addOpen = signal(false);
  addName = signal('');
  addDesc = signal('');
  addTags = signal('');
  addAliases = signal('');
  addWtLatency = signal('');
  addWtAccuracy = signal('');
  addWtCost = signal('');
  addWtQuality = signal('');
  addLoading = signal(false);
  addError = signal('');

  // ── Edit modal ────────────────────────────────────────────────────────────
  editTarget = signal<Model | null>(null);
  editName = signal('');
  editDesc = signal('');
  editTags = signal('');
  editAliases = signal('');
  editWtLatency = signal('');
  editWtAccuracy = signal('');
  editWtCost = signal('');
  editWtQuality = signal('');
  editCapFunctionCalling = signal(false);
  editCapVision = signal(false);
  editCapReasoning = signal(false);
  editLoading = signal(false);
  editError = signal('');

  // ── Computed ─────────────────────────────────────────────────────────────
  filteredModels = computed(() => {
    const q = this.search().toLowerCase().trim();
    const list = q
      ? this.models().filter(
          (m) =>
            m.name.toLowerCase().includes(q) ||
            (m.description ?? '').toLowerCase().includes(q) ||
            (m.tags ?? '').toLowerCase().includes(q) ||
            (m.aliases ?? '').toLowerCase().includes(q),
        )
      : this.models();
    const dir = this.lastUsedSort();
    if (dir === 'none') return list;
    // ISO-8601 UTC timestamps sort lexicographically; the empty string (never
    // used) lands first in ascending order, surfacing the quietest models.
    return [...list].sort((a, b) =>
      dir === 'asc'
        ? (a.last_used_at ?? '').localeCompare(b.last_used_at ?? '')
        : (b.last_used_at ?? '').localeCompare(a.last_used_at ?? ''),
    );
  });

  addValid = computed(() => this.addName().trim().length > 0);

  /** True while the model being edited has a manual capability override. */
  editTargetManualOverride = computed(() => {
    const target = this.editTarget();
    if (!target) return false;
    return this.getCapabilities(target.id)?.manual_override ?? false;
  });

  /**
   * Splits the comma-separated alias input into a clean list. Aliases are
   * trimmed, de-duplicated case-insensitively, and empty entries are dropped.
   */
  private parseAliases(text: string): string[] {
    const seen = new Set<string>();
    const aliases: string[] = [];
    for (const raw of text.split(',')) {
      const alias = raw.trim();
      if (!alias) continue;
      const key = alias.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      aliases.push(alias);
    }
    return aliases;
  }

  ngOnInit(): void {
    this.fetchModels();
  }

  async fetchModels(): Promise<void> {
  this.loading.set(true);
  this.loadError.set(false);

  try {
    const models = await this.modelService.getModels();
    this.models.set(models);

    const capabilities = await this.modelService.getModelCapabilities(
      models.map((model) => model.id),
    );

    this.capabilities.set(capabilities);
  } catch {
    this.loadError.set(true);
  } finally {
    this.loading.set(false);
  }
}
      
  getCapabilities(modelId: number): ModelCapability | undefined {
    return this.capabilities()[modelId];
  }

  // ── Last used ─────────────────────────────────────────────────────────────
  /** Cycles unsorted → oldest first (deprecation candidates) → newest first. */
  toggleLastUsedSort(): void {
    this.lastUsedSort.update((dir) => (dir === 'none' ? 'asc' : dir === 'asc' ? 'desc' : 'none'));
  }

  formatLastUsed(iso: string | null | undefined): string {
    return formatLastUsedLabel(iso);
  }

  isStaleModel(iso: string | null | undefined): boolean {
    return iso == null || daysSince(iso) >= Models.STALE_AFTER_DAYS;
  }

  /** Tooltip explaining why the model is highlighted; null while it is fresh. */
  lastUsedTooltip(iso: string | null | undefined): string | null {
    if (!this.isStaleModel(iso)) return null;
    if (iso == null) return 'Never used';
    return `Not used for ${daysSince(iso)} days`;
  }

  openReport(model: Model): void {
    this.router.navigate(['/models', model.id, 'details']);
  }

  // ── Delete flow ───────────────────────────────────────────────────────────
  openDeleteDialog(model: Model): void {
    this.deleteTarget.set(model);
    this.deleteError.set(false);
  }

  closeDeleteDialog(): void {
    if (this.deleteLoading()) return;
    this.deleteTarget.set(null);
  }

  async confirmDelete(): Promise<void> {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    try {
      await this.modelService.deleteModel(target.id);
      this.models.update((list) => list.filter((m) => m.id !== target.id));
      this.deleteTarget.set(null);
    } catch {
      this.deleteError.set(true);
    } finally {
      this.deleteLoading.set(false);
    }
  }

  // ── Add flow ──────────────────────────────────────────────────────────────
  openAddDialog(): void {
    this.addName.set('');
    this.addDesc.set('');
    this.addTags.set('');
    this.addAliases.set('');
    this.addWtLatency.set('');
    this.addWtAccuracy.set('');
    this.addWtCost.set('');
    this.addWtQuality.set('');
    this.addError.set('');
    this.addOpen.set(true);
  }

  closeAddDialog(): void {
    if (this.addLoading()) return;
    this.addOpen.set(false);
  }

  async submitAdd(): Promise<void> {
    if (!this.addValid() || this.addLoading()) return;
    this.addLoading.set(true);
    this.addError.set('');

    const payload: AddModelPayload = {
      name: this.addName().trim(),
      description: this.addDesc().trim() || undefined,
      tags: this.addTags().trim() || undefined,
      aliases: this.parseAliases(this.addAliases()),
    };

    const wtLatency = this.addWtLatency() ? Number(this.addWtLatency()) : undefined;
    const wtAccuracy = this.addWtAccuracy() ? Number(this.addWtAccuracy()) : undefined;
    const wtCost = this.addWtCost() ? Number(this.addWtCost()) : undefined;
    const wtQuality = this.addWtQuality() ? Number(this.addWtQuality()) : undefined;
    const hasWeights =
      wtLatency != null || wtAccuracy != null || wtCost != null || wtQuality != null;

    try {
      const newModelId = await this.modelService.addModel(payload);
      if (hasWeights) {
        await this.modelService.updateModel({
          model_id: newModelId,
          weight_latency: wtLatency,
          weight_accuracy: wtAccuracy,
          weight_cost: wtCost,
          weight_quality: wtQuality,
        });
      }
      await this.fetchModels();
      this.addOpen.set(false);
    } catch {
      this.addError.set('Failed to add model, please try again.');
    } finally {
      this.addLoading.set(false);
    }
  }

  // ── Edit flow ─────────────────────────────────────────────────────────────
  openEditDialog(model: Model): void {
    this.editTarget.set(model);
    this.editName.set(model.name ?? '');
    this.editDesc.set(model.description ?? '');
    this.editTags.set(model.tags ?? '');
    this.editAliases.set(model.aliases ?? '');
    this.editWtLatency.set(model.weight_latency != null ? String(model.weight_latency) : '');
    this.editWtAccuracy.set(model.weight_accuracy != null ? String(model.weight_accuracy) : '');
    this.editWtCost.set(model.weight_cost != null ? String(model.weight_cost) : '');
    this.editWtQuality.set(model.weight_quality != null ? String(model.weight_quality) : '');
    const caps = this.getCapabilities(model.id);
    this.editCapFunctionCalling.set(caps?.supports_function_calling ?? false);
    this.editCapVision.set(caps?.supports_vision ?? false);
    this.editCapReasoning.set(caps?.supports_reasoning ?? false);
    this.editError.set('');
  }

  closeEditDialog(): void {
    if (this.editLoading()) return;
    this.editTarget.set(null);
  }

  async submitEdit(): Promise<void> {
    const target = this.editTarget();
    if (!target || this.editLoading()) return;
    this.editLoading.set(true);
    this.editError.set('');
    const payload: UpdateModelPayload = {
      model_id: target.id,
      name: this.editName().trim() || undefined,
      description: this.editDesc().trim() || undefined,
      tags: this.editTags().trim() || undefined,
      aliases: this.parseAliases(this.editAliases()),
      weight_latency: this.editWtLatency() ? Number(this.editWtLatency()) : undefined,
      weight_accuracy: this.editWtAccuracy() ? Number(this.editWtAccuracy()) : undefined,
      weight_cost: this.editWtCost() ? Number(this.editWtCost()) : undefined,
      weight_quality: this.editWtQuality() ? Number(this.editWtQuality()) : undefined,
    };
    const storedCaps = this.getCapabilities(target.id);
    const capsChanged =
      this.editCapFunctionCalling() !== (storedCaps?.supports_function_calling ?? false) ||
      this.editCapVision() !== (storedCaps?.supports_vision ?? false) ||
      this.editCapReasoning() !== (storedCaps?.supports_reasoning ?? false);
    try {
      // Persist a changed capability override BEFORE the model info update:
      // renaming the model triggers an async catalog re-sync, which must see
      // manual_override=true and therefore skip the row.
      if (capsChanged) {
        const caps = await this.modelService.setModelCapabilities(
          target.id,
          this.editCapFunctionCalling(),
          this.editCapVision(),
          this.editCapReasoning(),
        );
        this.applyCapabilityState(caps);
      }
      await this.modelService.updateModel(payload);
      this.models.update((list) =>
        list.map((m) =>
          m.id === target.id
            ? {
                ...m,
                name: payload.name ?? m.name,
                description: payload.description ?? m.description,
                tags: payload.tags ?? m.tags,
                aliases: payload.aliases ? payload.aliases.join(', ') : m.aliases,
                weight_latency: payload.weight_latency ?? m.weight_latency,
                weight_accuracy: payload.weight_accuracy ?? m.weight_accuracy,
                weight_cost: payload.weight_cost ?? m.weight_cost,
                weight_quality: payload.weight_quality ?? m.weight_quality,
              }
            : m,
        ),
      );
      this.editTarget.set(null);
    } catch {
      this.editError.set('Failed to save changes, please try again.');
    } finally {
      this.editLoading.set(false);
    }
  }

  // Checkbox change handlers (the [checked] binding and the toggle keep the
  // signal in sync with the input; same idiom as the api-key permission rows).
  toggleCapFunctionCalling(): void {
    this.editCapFunctionCalling.update((v) => !v);
  }

  toggleCapVision(): void {
    this.editCapVision.update((v) => !v);
  }

  toggleCapReasoning(): void {
    this.editCapReasoning.update((v) => !v);
  }

  /** Clear the manual capability override and re-sync from the catalog. */
  async resetCapabilities(): Promise<void> {
    const target = this.editTarget();
    if (!target || this.editLoading()) return;
    this.editLoading.set(true);
    this.editError.set('');
    try {
      const state = await this.modelService.resetModelCapabilities(target.id);
      this.applyCapabilityState(state);
      // Mirror the re-synced catalog values into the dialog; with
      // manual_override now false the badge and the reset button disappear.
      this.editCapFunctionCalling.set(state.supports_function_calling);
      this.editCapVision.set(state.supports_vision);
      this.editCapReasoning.set(state.supports_reasoning);
    } catch {
      this.editError.set('Failed to reset capabilities, please try again.');
    } finally {
      this.editLoading.set(false);
    }
  }

  /** Merge a set/reset state map into the local capabilities record. */
  private applyCapabilityState(state: ModelCapabilityState): void {
    this.capabilities.update((all) => ({
      ...all,
      [state.model_id]: {
        id: all[state.model_id]?.id ?? 0,
        model_id: state.model_id,
        supports_function_calling: state.supports_function_calling,
        supports_vision: state.supports_vision,
        supports_reasoning: state.supports_reasoning,
        manual_override: state.manual_override,
      },
    }));
  }
}
