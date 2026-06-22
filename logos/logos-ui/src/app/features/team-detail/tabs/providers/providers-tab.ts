import { Component, Input, OnInit, signal, computed, inject } from '@angular/core';
import { forkJoin } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { ModalFormComponent } from '../../../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import { SearchInputComponent } from '../../../../shared/components/search-input/search-input';
import { ProviderItem } from '../../../../shared/models/team.model';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';

@Component({
  selector: 'app-providers-tab',
  standalone: true,
  imports: [FormsModule, ModalFormComponent, ModalConfirmComponent, DataTableComponent, SearchInputComponent, ErrorMessageComponent],
  templateUrl: './providers-tab.html',
  styleUrl: './providers-tab.scss',
})
export class ProvidersTabComponent implements OnInit {
  @Input() teamId!: number;
  @Input() canEdit = false;

  private teamService = inject(TeamManagementService);

  allProviders   = signal<ProviderItem[]>([]);
  assignedIds    = signal<Set<number>>(new Set());
  loading        = signal(true);
  error          = signal(false);

  get assigned(): ProviderItem[] {
    const ids = this.assignedIds();
    return this.allProviders().filter(p => ids.has(p.id));
  }

  get available(): ProviderItem[] {
    const ids = this.assignedIds();
    return this.allProviders().filter(p => !ids.has(p.id));
  }

  // ── Add dialog ─────────────────────────────────────────────────────────────
  addOpen      = signal(false);
  search       = signal('');
  stagedIds    = signal<Set<number>>(new Set());
  saving       = signal(false);
  saveError    = signal('');

  get filteredAvailable(): ProviderItem[] {
    const q = this.search().toLowerCase().trim();
    const list = this.available;
    if (!q) return list;
    return list.filter(p => p.name.toLowerCase().includes(q));
  }

  get stagedCount(): number { return this.stagedIds().size; }

  isStaged(id: number): boolean { return this.stagedIds().has(id); }

  toggleStage(id: number): void {
    const next = new Set(this.stagedIds());
    if (next.has(id)) next.delete(id); else next.add(id);
    this.stagedIds.set(next);
  }

  openAddDialog(): void {
    this.search.set('');
    this.stagedIds.set(new Set());
    this.saveError.set('');
    this.addOpen.set(true);
  }

  confirmAdd(): void {
    if (this.stagedCount === 0 || this.saving()) return;
    const newIds = [...this.assignedIds(), ...this.stagedIds()];
    this.saving.set(true);
    this.saveError.set('');
    this.teamService.setTeamProviderPermissions(this.teamId, newIds).subscribe({
      next: () => {
        this.assignedIds.set(new Set(newIds));
        this.saving.set(false);
        this.addOpen.set(false);
      },
      error: () => {
        this.saveError.set('Failed to update providers, please try again.');
        this.saving.set(false);
      },
    });
  }

  // ── Remove confirm dialog ──────────────────────────────────────────────────
  confirmOpen    = signal(false);
  pendingRemove  = signal<{ id: number; name: string } | null>(null);
  removing       = signal(false);
  removeError    = signal('');

  promptRemove(p: ProviderItem): void {
    this.pendingRemove.set({ id: p.id, name: p.name });
    this.removeError.set('');
    this.confirmOpen.set(true);
  }

  executeRemove(): void {
    const target = this.pendingRemove();
    if (!target || this.removing()) return;
    const newIds = [...this.assignedIds()].filter(id => id !== target.id);
    this.removing.set(true);
    this.removeError.set('');
    this.teamService.setTeamProviderPermissions(this.teamId, newIds).subscribe({
      next: () => {
        this.assignedIds.set(new Set(newIds));
        this.removing.set(false);
        this.confirmOpen.set(false);
        this.pendingRemove.set(null);
      },
      error: () => {
        this.removeError.set('Failed to remove provider, please try again.');
        this.removing.set(false);
      },
    });
  }

  ngOnInit(): void {
    forkJoin({
      all:     this.teamService.getAllProviders(),
      enabled: this.teamService.getTeamProviderPermissions(this.teamId),
    }).subscribe({
      next: ({ all, enabled }) => {
        this.allProviders.set(all);
        this.assignedIds.set(new Set(enabled));
        this.loading.set(false);
      },
      error: () => { this.error.set(true); this.loading.set(false); },
    });
  }
}
