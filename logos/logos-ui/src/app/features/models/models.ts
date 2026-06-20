import { Component, computed, inject, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { switchMap, of } from 'rxjs';
import { Dialog } from 'primeng/dialog';
import { ModelManagementService } from '../../core/services/model-management.service';
import { Model, AddModelPayload, UpdateModelPayload } from '../../shared/models/model.model';
import { SearchInputComponent } from '../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { AddButton } from '../../shared/components/add-button/add-button';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';

@Component({
  selector: 'app-models',
  standalone: true,
  imports: [FormsModule, Dialog, SearchInputComponent, DataTableComponent, AddButton, ErrorMessageComponent],
  templateUrl: './models.html',
  styleUrl: './models.scss',
})
export class Models implements OnInit {
  private modelService = inject(ModelManagementService);

  // ── List state ──────────────────────────────────────────────────────────
  models    = signal<Model[]>([]);
  loading   = signal(true);
  search    = signal('');
  loadError = signal(false);

  // ── Delete modal ────────────────────────────────────────────────────────
  deleteTarget  = signal<Model | null>(null);
  deleteLoading = signal(false);
  deleteError   = signal(false);

  // ── Add modal ────────────────────────────────────────────────────────────
  addOpen       = signal(false);
  addName       = signal('');
  addDesc       = signal('');
  addTags       = signal('');
  addParallel   = signal('');
  addWtLatency  = signal('');
  addWtAccuracy = signal('');
  addWtCost     = signal('');
  addWtQuality  = signal('');
  addLoading    = signal(false);
  addError      = signal('');

  // ── Edit modal ────────────────────────────────────────────────────────────
  editTarget      = signal<Model | null>(null);
  editName        = signal('');
  editDesc        = signal('');
  editTags        = signal('');
  editParallel    = signal('');
  editWtLatency   = signal('');
  editWtAccuracy  = signal('');
  editWtCost      = signal('');
  editWtQuality   = signal('');
  editLoading     = signal(false);
  editError       = signal('');

  // ── Computed ─────────────────────────────────────────────────────────────
  filteredModels = computed(() => {
    const q = this.search().toLowerCase().trim();
    if (!q) return this.models();
    return this.models().filter(m =>
      m.name.toLowerCase().includes(q) ||
      (m.description ?? '').toLowerCase().includes(q) ||
      (m.tags ?? '').toLowerCase().includes(q)
    );
  });

  addValid = computed(() => this.addName().trim().length > 0);

  ngOnInit(): void {
    this.fetchModels();
  }

  fetchModels(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.modelService.getModels().subscribe({
      next: models => { this.models.set(models); this.loading.set(false); },
      error: ()     => { this.loadError.set(true); this.loading.set(false); },
    });
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

  confirmDelete(): void {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    this.modelService.deleteModel(target.id).subscribe({
      next: () => {
        this.models.update(list => list.filter(m => m.id !== target.id));
        this.deleteLoading.set(false);
        this.deleteTarget.set(null);
      },
      error: () => {
        this.deleteLoading.set(false);
        this.deleteError.set(true);
      },
    });
  }

  // ── Add flow ──────────────────────────────────────────────────────────────
  openAddDialog(): void {
    this.addName.set('');
    this.addDesc.set('');
    this.addTags.set('');
    this.addParallel.set('');
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

  submitAdd(): void {
    if (!this.addValid() || this.addLoading()) return;
    this.addLoading.set(true);
    this.addError.set('');

    const payload: AddModelPayload = {
      name: this.addName().trim(),
      description: this.addDesc().trim() || undefined,
      tags: this.addTags().trim() || undefined,
      parallel: this.addParallel() ? Number(this.addParallel()) : undefined,
    };

    const wtLatency  = this.addWtLatency()  ? Number(this.addWtLatency())  : undefined;
    const wtAccuracy = this.addWtAccuracy() ? Number(this.addWtAccuracy()) : undefined;
    const wtCost     = this.addWtCost()     ? Number(this.addWtCost())     : undefined;
    const wtQuality  = this.addWtQuality()  ? Number(this.addWtQuality())  : undefined;
    const hasWeights = wtLatency != null || wtAccuracy != null || wtCost != null || wtQuality != null;

    this.modelService.addModel(payload).pipe(
      switchMap(newModel => {
        if (!hasWeights) return of(newModel);
        const updatePayload: UpdateModelPayload = {
          model_id: newModel.id,
          weight_latency:  wtLatency,
          weight_accuracy: wtAccuracy,
          weight_cost:     wtCost,
          weight_quality:  wtQuality,
        };
        return this.modelService.updateModel(updatePayload);
      }),
    ).subscribe({
      next: () => {
        this.fetchModels();
        this.addLoading.set(false);
        this.addOpen.set(false);
      },
      error: () => {
        this.addLoading.set(false);
        this.addError.set('Failed to add model, please try again.');
      },
    });
  }

  // ── Edit flow ─────────────────────────────────────────────────────────────
  openEditDialog(model: Model): void {
    this.editTarget.set(model);
    this.editName.set(model.name ?? '');
    this.editDesc.set(model.description ?? '');
    this.editTags.set(model.tags ?? '');
    this.editParallel.set(model.parallel != null ? String(model.parallel) : '');
    this.editWtLatency.set(model.weight_latency != null ? String(model.weight_latency) : '');
    this.editWtAccuracy.set(model.weight_accuracy != null ? String(model.weight_accuracy) : '');
    this.editWtCost.set(model.weight_cost != null ? String(model.weight_cost) : '');
    this.editWtQuality.set(model.weight_quality != null ? String(model.weight_quality) : '');
    this.editError.set('');
  }

  closeEditDialog(): void {
    if (this.editLoading()) return;
    this.editTarget.set(null);
  }

  submitEdit(): void {
    const target = this.editTarget();
    if (!target || this.editLoading()) return;
    this.editLoading.set(true);
    this.editError.set('');
    const payload: UpdateModelPayload = {
      model_id: target.id,
      name: this.editName().trim() || undefined,
      description: this.editDesc().trim() || undefined,
      tags: this.editTags().trim() || undefined,
      parallel: this.editParallel() ? Number(this.editParallel()) : undefined,
      weight_latency: this.editWtLatency() ? Number(this.editWtLatency()) : undefined,
      weight_accuracy: this.editWtAccuracy() ? Number(this.editWtAccuracy()) : undefined,
      weight_cost: this.editWtCost() ? Number(this.editWtCost()) : undefined,
      weight_quality: this.editWtQuality() ? Number(this.editWtQuality()) : undefined,
    };
    this.modelService.updateModel(payload).subscribe({
      next: updated => {
        this.models.update(list => list.map(m => m.id === updated.id ? updated : m));
        this.editLoading.set(false);
        this.editTarget.set(null);
      },
      error: () => {
        this.editLoading.set(false);
        this.editError.set('Failed to save changes, please try again.');
      },
    });
  }
}
