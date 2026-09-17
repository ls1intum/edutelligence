import {
  Component,
  computed,
  inject,
  signal,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { ModelManagementService } from '../../core/services/model-management.service';
import { TeamManagementService } from '../../core/services/team-management.service';
import {
  ModelAccessResponse,
  TeamAccess,
  KeyAccess,
} from '../../shared/models/model-access.model';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { formatLastUsed as formatLastUsedLabel } from '../../shared/utils/date';

/**
 * Admin view for a single model: where it is hosted, and which teams /
 * custom-permission keys actually have both the model grant and a grant for
 * a hosting provider. Orphaned grants (model grant without any reachable
 * provider) are highlighted, and team-provider grants can be granted or
 * revoked right here by toggling a checkbox — each change is one atomic
 * backend operation that keeps the team's other grants.
 */
@Component({
  selector: 'app-model-access',
  standalone: true,
  imports: [RouterModule, DataTableComponent, ErrorMessageComponent],
  templateUrl: './model-access.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './model-access.scss',
})
export class ModelAccess implements OnInit {
  private route = inject(ActivatedRoute);
  private modelService = inject(ModelManagementService);
  private teamService = inject(TeamManagementService);

  access = signal<ModelAccessResponse | null>(null);
  loading = signal(true);
  loadError = signal(false);
  /** One grant toggle in flight; all checkboxes stay disabled meanwhile. */
  toggling = signal(false);
  toggleError = signal<string | null>(null);

  /** Provider columns of the matrix, e.g. "Logos Mac1". */
  readonly providerColumns = computed(() =>
    this.access()?.providers.map((p) => p.name.toUpperCase()) ?? [],
  );

  /** One track column per hosting provider, plus the fixed columns. */
  readonly teamColumns = computed(() => [
    'TEAM',
    'MODEL',
    ...this.providerColumns(),
    'STATUS',
  ]);

  readonly keyColumns = computed(() => [
    'KEY',
    'TEAM',
    'ACTIVE',
    'MODEL',
    ...this.providerColumns(),
    'STATUS',
  ]);

  readonly teamGridCols = computed(() =>
    `${240}fr 90fr ${'90fr '.repeat(this.providerColumns().length).trim()} 150fr`,
  );

  readonly keyGridCols = computed(() =>
    `220fr 160fr 80fr 90fr ${'90fr '.repeat(this.providerColumns().length).trim()} 150fr`,
  );

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.load(id);
  }

  async load(modelId: number): Promise<void> {
    this.loading.set(true);
    this.loadError.set(false);
    try {
      this.access.set(await this.modelService.getModelAccess(modelId));
    } catch {
      this.loadError.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Toggle a team-provider grant in the matrix. Both directions are single
   * atomic backend operations (idempotent upsert / single-row delete), never
   * a full-set PUT — the team's other grants are preserved by construction
   * and a concurrent admin edit can neither be clobbered nor trigger the
   * model-grant cascade. The matrix is then reloaded with the usual
   * loading/error feedback.
   */
  async toggleProviderGrant(teamId: number, providerId: number, granted: boolean): Promise<void> {
    if (this.toggling()) return;
    this.toggling.set(true);
    this.toggleError.set(null);
    try {
      if (granted) {
        await this.teamService.removeTeamProviderPermission(teamId, providerId);
      } else {
        await this.teamService.addTeamProviderPermission(teamId, providerId);
      }
      const id = Number(this.route.snapshot.paramMap.get('id'));
      await this.load(id);
    } catch {
      this.toggleError.set('Failed to update the provider grant, please try again.');
    } finally {
      this.toggling.set(false);
    }
  }

  // ── Matrix helpers ───────────────────────────────────────────────────────
  /**
   * Model grant without any host-provider grant: can never route. Derived
   * from the grants themselves, NOT from effective_access — an inactive key
   * holds both grants (so it is not orphaned, just inactive), while
   * effective_access is false for it as well.
   */
  isOrphaned(entry: TeamAccess | KeyAccess): boolean {
    return entry.model_grant && !entry.provider_grants.some((g) => g.granted);
  }

  /** Host-provider grant without the model grant: secondary signal. */
  isProviderOnly(entry: TeamAccess | KeyAccess): boolean {
    return (
      !entry.model_grant &&
      !entry.effective_access &&
      entry.provider_grants.some((g) => g.granted)
    );
  }

  // ── Formatting ───────────────────────────────────────────────────────────
  formatLastUsed(iso: string | null | undefined): string {
    return formatLastUsedLabel(iso);
  }
}
