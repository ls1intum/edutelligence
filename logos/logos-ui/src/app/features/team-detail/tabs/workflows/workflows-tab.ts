import {
  AfterViewChecked,
  ChangeDetectionStrategy,
  Component,
  Input,
  OnChanges,
  inject,
  signal,
} from '@angular/core';
import { DecimalPipe, SlicePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import {
  AiLlmCallRecommendation,
  AiWorkflow,
  RecommendedSla,
  TeamApiKey,
  TeamWorkflowsResponse,
} from '../../../../shared/models/team.model';
import { KeySla, SLA_OPTIONS } from '../key-sla';

/**
 * Team → Workflows.
 *
 * Latest AI-workflow analyses for linked repositories: Mermaid diagrams and
 * SLA recommendations that owners can accept, override, or reject.
 */
@Component({
  selector: 'app-workflows-tab',
  standalone: true,
  imports: [FormsModule, DecimalPipe, SlicePipe, DataTableComponent, ErrorMessageComponent],
  templateUrl: './workflows-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './workflows-tab.scss',
})
export class WorkflowsTabComponent implements OnChanges, AfterViewChecked {
  @Input() teamId!: number;
  @Input() canEdit = false;
  @Input() apiKeys: TeamApiKey[] = [];

  private teamService = inject(TeamManagementService);
  private diagramsDirty = false;
  private mermaidReady: Promise<typeof import('mermaid')> | null = null;

  loading = signal(true);
  loadError = signal('');
  actionError = signal('');
  data = signal<TeamWorkflowsResponse | null>(null);
  reviewingId = signal<number | null>(null);
  overrideSla = signal<Record<number, KeySla>>({});
  acceptKeyId = signal<Record<number, number | ''>>({});

  readonly slaOptions = SLA_OPTIONS;
  readonly recCols = [
    'File',
    'Model',
    'Recommended',
    'Confidence',
    'Status',
    '',
  ];
  readonly recGrid =
    'minmax(8rem, 1.4fr) minmax(5rem, 0.8fr) minmax(5rem, 0.7fr) minmax(4rem, 0.5fr) minmax(5rem, 0.6fr) minmax(10rem, auto)';

  ngOnChanges(): void {
    if (this.teamId) {
      void this.load();
    }
  }

  ngAfterViewChecked(): void {
    if (!this.diagramsDirty) return;
    this.diagramsDirty = false;
    void this.renderDiagrams();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set('');
    try {
      this.data.set(await this.teamService.getTeamWorkflows(this.teamId));
      this.diagramsDirty = true;
    } catch {
      this.loadError.set('Failed to load workflows, please refresh.');
      this.data.set(null);
    } finally {
      this.loading.set(false);
    }
  }

  workflowsForRepo(repo: TeamWorkflowsResponse['repositories'][number]): AiWorkflow[] {
    return repo.workflows ?? [];
  }

  pendingRecs(): AiLlmCallRecommendation[] {
    return this.data()?.pending_recommendations ?? [];
  }

  async accept(rec: AiLlmCallRecommendation): Promise<void> {
    const keyPick = this.acceptKeyId()[rec.id];
    const apiKeyId =
      typeof keyPick === 'number'
        ? keyPick
        : rec.api_key_id ?? undefined;
    await this.review(rec, {
      action: 'accept',
      api_key_id: apiKeyId,
    });
  }

  async override(rec: AiLlmCallRecommendation): Promise<void> {
    const sla = this.overrideSla()[rec.id] ?? rec.recommended_sla;
    const keyPick = this.acceptKeyId()[rec.id];
    const apiKeyId =
      typeof keyPick === 'number'
        ? keyPick
        : rec.api_key_id ?? undefined;
    await this.review(rec, {
      action: 'override',
      confirmed_sla: sla,
      api_key_id: apiKeyId,
    });
  }

  async reject(rec: AiLlmCallRecommendation): Promise<void> {
    await this.review(rec, { action: 'reject' });
  }

  setOverrideSla(recId: number, value: string): void {
    this.overrideSla.update((m) => ({ ...m, [recId]: value as KeySla }));
  }

  setAcceptKey(recId: number, value: string | number): void {
    if (value === '' || value == null) {
      this.acceptKeyId.update((m) => ({ ...m, [recId]: '' }));
      return;
    }
    const parsed = Number(value);
    this.acceptKeyId.update((m) => ({ ...m, [recId]: Number.isNaN(parsed) ? '' : parsed }));
  }

  keySelectValue(rec: AiLlmCallRecommendation): number | '' {
    const picked = this.acceptKeyId()[rec.id];
    if (picked !== undefined) return picked;
    return rec.api_key_id ?? '';
  }

  private async review(
    rec: AiLlmCallRecommendation,
    payload: {
      action: 'accept' | 'override' | 'reject';
      confirmed_sla?: RecommendedSla;
      api_key_id?: number;
    },
  ): Promise<void> {
    if (this.reviewingId() != null) return;
    this.reviewingId.set(rec.id);
    this.actionError.set('');
    try {
      await this.teamService.reviewRecommendation(this.teamId, rec.id, payload);
      await this.load();
    } catch (err: unknown) {
      const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
      this.actionError.set(
        typeof detail === 'string' ? detail : 'Failed to review recommendation.',
      );
    } finally {
      this.reviewingId.set(null);
    }
  }

  private async renderDiagrams(): Promise<void> {
    try {
      if (!this.mermaidReady) {
        this.mermaidReady = import('mermaid');
      }
      const mod = await this.mermaidReady;
      const mermaid = mod.default;
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });
      await mermaid.run({ querySelector: '.workflows-tab .mermaid' });
    } catch {
      // Leave <pre class="mermaid"> source visible if render fails or mermaid is unavailable.
    }
  }
}
