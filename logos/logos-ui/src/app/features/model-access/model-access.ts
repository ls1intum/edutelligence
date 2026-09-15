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
import {
  ModelAccessResponse,
  TeamAccess,
  KeyAccess,
} from '../../shared/models/model-access.model';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { formatLastUsed as formatLastUsedLabel } from '../../shared/utils/date';

/**
 * Read-only admin view for a single model: where it is hosted, and which
 * teams / custom-permission keys actually have both the model grant and a
 * grant for a hosting provider. Orphaned grants (model grant without any
 * reachable provider) are highlighted — granting itself stays on the team
 * detail pages.
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

  access = signal<ModelAccessResponse | null>(null);
  loading = signal(true);
  loadError = signal(false);

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

  // ── Matrix helpers ───────────────────────────────────────────────────────
  /** Model grant without any host-provider grant: can never route. */
  isOrphaned(entry: TeamAccess | KeyAccess): boolean {
    return entry.model_grant && !entry.effective_access;
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

  formatPrice(usdPerMillion: number | null): string {
    return usdPerMillion != null ? `$${usdPerMillion.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')}` : '–';
  }

  formatTokens(tokens: number | null): string {
    return tokens != null ? `${tokens.toLocaleString()} tokens` : '–';
  }
}
