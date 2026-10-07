import {
  AfterViewChecked,
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  effect,
  inject,
  signal,
} from '@angular/core';
import { DecimalPipe, SlicePipe, TitleCasePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import { ModelProfileRadarComponent } from '../../../../shared/components/model-profile-radar/model-profile-radar';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { ModelManagementService } from '../../../../core/services/model-management.service';
import { ThemeService } from '../../../../core/services/theme.service';
import {
  AiLlmCallRecommendation,
  AiWorkflow,
  ObjectiveKey,
  RecommendedSlo,
  TeamApiKey,
  TeamWorkflowsResponse,
} from '../../../../shared/models/team.model';
import { Model } from '../../../../shared/models/model.model';
import { KeySlo, SLO_OPTIONS } from '../key-slo';
import { quoteFlowchartLabels } from './mermaid-labels';

const OBJECTIVE_KEYS: ObjectiveKey[] = ['latency', 'quality', 'price'];

function defaultPriorityForSlo(slo: string | null | undefined): ObjectiveKey[] {
  switch ((slo ?? '').trim()) {
    case 'ux-critical':
      return ['latency', 'quality', 'price'];
    case 'ux-background':
      return ['price', 'quality', 'latency'];
    default:
      return ['quality', 'latency', 'price'];
  }
}

function normalizePriority(raw: string[] | null | undefined, slo?: string): ObjectiveKey[] {
  const seen = new Set<string>();
  const ordered: ObjectiveKey[] = [];
  for (const item of raw ?? []) {
    const key = String(item).trim().toLowerCase();
    if ((OBJECTIVE_KEYS as string[]).includes(key) && !seen.has(key)) {
      ordered.push(key as ObjectiveKey);
      seen.add(key);
    }
  }
  if (ordered.length === 0) {
    return defaultPriorityForSlo(slo);
  }
  for (const key of OBJECTIVE_KEYS) {
    if (!seen.has(key)) ordered.push(key);
  }
  return ordered;
}

/**
 * Team → Workflows.
 *
 * Latest AI-workflow analyses for linked repositories: Mermaid diagrams and
 * SLO / objective-priority recommendations that owners can accept, override,
 * or reject.
 */
@Component({
  selector: 'app-workflows-tab',
  standalone: true,
  imports: [
    FormsModule,
    DecimalPipe,
    SlicePipe,
    TitleCasePipe,
    DataTableComponent,
    ErrorMessageComponent,
    ModelProfileRadarComponent,
  ],
  templateUrl: './workflows-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './workflows-tab.scss',
})
export class WorkflowsTabComponent implements OnChanges, AfterViewChecked {
  @Input() teamId!: number;
  @Input() canEdit = false;
  @Input() apiKeys: TeamApiKey[] = [];
  /** Fired when a review updates an application key's SLO priority. */
  @Output() keysChanged = new EventEmitter<void>();

  private teamService = inject(TeamManagementService);
  private modelService = inject(ModelManagementService);
  private theme = inject(ThemeService);
  private diagramsDirty = false;
  private mermaidReady: Promise<typeof import('mermaid')> | null = null;
  /** Avoid wiping diagrams on the first theme effect before load() paints them. */
  private themeWatchStarted = false;
  /** Bumped on theme toggle so Angular re-runs AfterViewChecked to re-paint Mermaid. */
  private readonly diagramEpoch = signal(0);

  loading = signal(true);
  loadError = signal('');
  actionError = signal('');
  data = signal<TeamWorkflowsResponse | null>(null);
  reviewingId = signal<number | null>(null);
  overrideSlo = signal<Record<number, KeySlo>>({});
  overridePriority = signal<Record<number, ObjectiveKey[]>>({});
  /** The key Accept / Override apply to; null until the owner picks one (then the default applies). */
  private reviewKeyPick = signal<number | '' | null>(null);
  savingModelId = signal<number | null>(null);
  /** Workflow id currently being edited in the Mermaid textarea. */
  editingDiagramId = signal<number | null>(null);
  /** Draft Mermaid while editing; keyed by workflow id. */
  diagramDraft = signal<Record<number, string>>({});
  savingDiagramId = signal<number | null>(null);
  reviewingProposalId = signal<number | null>(null);
  /** name/alias (lower) → model, for spider charts beside detected models */
  private modelsByName = signal<Map<string, Model>>(new Map());

  readonly sloOptions = SLO_OPTIONS;
  readonly recCols = [
    'File',
    'Model',
    'Recommended',
    'Confidence',
    'Status',
    '',
  ];
  // No `auto` track: every row is its own grid, so a content-sized column
  // would size differently per row and drift away from the header.
  readonly recGrid =
    'minmax(10rem, 1.6fr) minmax(12rem, 1fr) minmax(9rem, 1fr) 6.5rem 7.5rem 21rem';

  constructor() {
    // Mermaid paints node fills/text at initialize time; follow Logos theme.
    effect(() => {
      this.theme.isDark();
      if (!this.themeWatchStarted) {
        this.themeWatchStarted = true;
        return;
      }
      this.diagramsDirty = true;
      this.diagramEpoch.update((n) => n + 1);
    });
  }

  ngOnChanges(): void {
    if (this.teamId) {
      void this.load();
    }
  }

  ngAfterViewChecked(): void {
    if (!this.diagramsDirty) return;
    this.diagramsDirty = false;
    this.resetProcessedDiagrams();
    void this.renderDiagrams();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set('');
    try {
      const [workflows, models] = await Promise.all([
        this.teamService.getTeamWorkflows(this.teamId),
        this.modelService.getModels().catch(() => [] as Model[]),
      ]);
      this.data.set(workflows);
      this.modelsByName.set(this.indexModels(models));
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

  priorityFor(rec: AiLlmCallRecommendation): ObjectiveKey[] {
    const edited = this.overridePriority()[rec.id];
    if (edited) return edited;
    if (rec.review_status !== 'pending' && rec.confirmed_objective_priority?.length) {
      return normalizePriority(rec.confirmed_objective_priority, rec.confirmed_slo ?? rec.recommended_slo);
    }
    return normalizePriority(rec.objective_priority, rec.recommended_slo);
  }

  movePriority(recId: number, index: number, dir: -1 | 1): void {
    const rec = this.findRec(recId);
    if (!rec) return;
    const list = [...this.priorityFor(rec)];
    const j = index + dir;
    if (j < 0 || j >= list.length) return;
    [list[index], list[j]] = [list[j], list[index]];
    this.overridePriority.update((m) => ({ ...m, [recId]: list }));
  }

  ratingsForDetectedModel(name: string | null | undefined): Record<string, number> | null {
    if (!name?.trim()) return null;
    const model = this.modelsByName().get(name.trim().toLowerCase());
    const ratings = model?.profile_ratings;
    if (!ratings || Object.keys(ratings).length === 0) return null;
    return ratings;
  }

  /** Team keys, highest queue priority first; a production key wins a tie. */
  keysByPriority(): TeamApiKey[] {
    const isProd = (k: TeamApiKey) => /prod/i.test(k.environment ?? '') || /prod/i.test(k.name);
    return [...this.apiKeys].sort(
      (a, b) =>
        (b.default_priority ?? 0) - (a.default_priority ?? 0) ||
        Number(isProd(b)) - Number(isProd(a)) ||
        a.id - b.id,
    );
  }

  reviewKeyValue(): number | '' {
    const picked = this.reviewKeyPick();
    if (picked !== null) return picked;
    return this.keysByPriority()[0]?.id ?? '';
  }

  setReviewKey(value: string | number): void {
    const parsed = Number(value);
    this.reviewKeyPick.set(value === '' || value == null || Number.isNaN(parsed) ? '' : parsed);
  }

  /** Model names to pick from, plus whatever the analysis guessed if Logos does not know it. */
  modelOptions(rec: AiLlmCallRecommendation): string[] {
    const names = new Set([...this.modelsByName().values()].map((m) => m.name));
    const current = rec.detected_model?.trim();
    if (current) names.add(current);
    return [...names].sort((a, b) => a.localeCompare(b));
  }

  async setModel(rec: AiLlmCallRecommendation, value: string): Promise<void> {
    const model = value?.trim() || null;
    if (model === (rec.detected_model ?? null) || this.savingModelId() != null) return;
    this.savingModelId.set(rec.id);
    this.actionError.set('');
    try {
      const saved = await this.teamService.setRecommendationModel(this.teamId, rec.id, model);
      // Both lists hold their own copy of a pending recommendation.
      for (const r of this.allRecs()) {
        if (r.id === rec.id) r.detected_model = saved.detected_model ?? null;
      }
    } catch (err: unknown) {
      const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
      this.actionError.set(typeof detail === 'string' ? detail : 'Failed to save the model.');
    } finally {
      this.savingModelId.set(null);
    }
  }

  diagramSource(wf: AiWorkflow): string {
    return quoteFlowchartLabels(wf.diagram_mermaid ?? '');
  }

  proposedDiagramSource(wf: AiWorkflow): string {
    return quoteFlowchartLabels(wf.proposed_diagram_mermaid ?? '');
  }

  isEditingDiagram(wf: AiWorkflow): boolean {
    return this.editingDiagramId() === wf.id;
  }

  startEditDiagram(wf: AiWorkflow): void {
    this.editingDiagramId.set(wf.id);
    this.diagramDraft.update((m) => ({ ...m, [wf.id]: wf.diagram_mermaid ?? '' }));
    // Switching from another editor brings that workflow's <pre> back as source.
    this.diagramsDirty = true;
  }

  cancelEditDiagram(): void {
    this.editingDiagramId.set(null);
    // The restored <pre> holds Mermaid source until the next render pass.
    this.diagramsDirty = true;
  }

  setDiagramDraft(workflowId: number, value: string): void {
    this.diagramDraft.update((m) => ({ ...m, [workflowId]: value }));
  }

  async saveDiagram(wf: AiWorkflow): Promise<void> {
    if (this.savingDiagramId() != null) return;
    const draft = (this.diagramDraft()[wf.id] ?? '').trim();
    if (!draft) {
      this.actionError.set('Diagram Mermaid cannot be empty.');
      return;
    }
    this.savingDiagramId.set(wf.id);
    this.actionError.set('');
    try {
      const saved = await this.teamService.setWorkflowDiagram(this.teamId, wf.id, draft);
      this.applyWorkflow(saved);
      this.editingDiagramId.set(null);
      this.diagramsDirty = true;
    } catch (err: unknown) {
      const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
      this.actionError.set(typeof detail === 'string' ? detail : 'Failed to save the diagram.');
    } finally {
      this.savingDiagramId.set(null);
    }
  }

  async reviewDiagramProposal(wf: AiWorkflow, action: 'accept' | 'dismiss'): Promise<void> {
    if (this.reviewingProposalId() != null) return;
    this.reviewingProposalId.set(wf.id);
    this.actionError.set('');
    try {
      const saved = await this.teamService.reviewWorkflowDiagramProposal(this.teamId, wf.id, action);
      this.applyWorkflow(saved);
      this.diagramsDirty = true;
    } catch (err: unknown) {
      const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
      this.actionError.set(
        typeof detail === 'string' ? detail : 'Failed to review the diagram proposal.',
      );
    } finally {
      this.reviewingProposalId.set(null);
    }
  }

  async accept(rec: AiLlmCallRecommendation): Promise<void> {
    await this.review(rec, {
      action: 'accept',
      ...this.keyPayload(),
      confirmed_objective_priority: this.priorityFor(rec),
    });
  }

  async override(rec: AiLlmCallRecommendation): Promise<void> {
    const slo = this.overrideSlo()[rec.id] ?? rec.recommended_slo;
    await this.review(rec, {
      action: 'override',
      confirmed_slo: slo,
      confirmed_objective_priority: this.priorityFor(rec),
      ...this.keyPayload(),
    });
  }

  async reject(rec: AiLlmCallRecommendation): Promise<void> {
    await this.review(rec, { action: 'reject' });
  }

  setOverrideSlo(recId: number, value: string): void {
    this.overrideSlo.update((m) => ({ ...m, [recId]: value as KeySlo }));
  }

  /**
   * The key part of a review. The first review pins the default: a review
   * changes that key's priority, and recomputing "highest priority" after the
   * key refresh could otherwise hand the next review a different key.
   */
  private keyPayload(): { api_key_id: number } | { no_api_key: true } {
    const value = this.reviewKeyValue();
    if (this.reviewKeyPick() === null) this.reviewKeyPick.set(value);
    return typeof value === 'number' ? { api_key_id: value } : { no_api_key: true };
  }

  private allRecs(): AiLlmCallRecommendation[] {
    const data = this.data();
    if (!data) return [];
    return [...data.pending_recommendations, ...data.repositories.flatMap((r) => r.recommendations)];
  }

  private findRec(recId: number): AiLlmCallRecommendation | undefined {
    return this.allRecs().find((r) => r.id === recId);
  }

  private applyWorkflow(saved: AiWorkflow): void {
    const data = this.data();
    if (!data) return;
    for (const repo of data.repositories) {
      const idx = repo.workflows.findIndex((w) => w.id === saved.id);
      if (idx >= 0) {
        repo.workflows[idx] = { ...repo.workflows[idx], ...saved };
        this.data.set({ ...data });
        return;
      }
    }
  }

  private indexModels(models: Model[]): Map<string, Model> {
    const map = new Map<string, Model>();
    for (const m of models) {
      map.set(m.name.toLowerCase(), m);
      for (const alias of (m.aliases ?? '').split(',')) {
        const a = alias.trim().toLowerCase();
        if (a) map.set(a, m);
      }
    }
    return map;
  }

  private async review(
    rec: AiLlmCallRecommendation,
    payload: {
      action: 'accept' | 'override' | 'reject';
      confirmed_slo?: RecommendedSlo;
      confirmed_objective_priority?: ObjectiveKey[];
      api_key_id?: number;
      no_api_key?: boolean;
    },
  ): Promise<void> {
    if (this.reviewingId() != null) return;
    this.reviewingId.set(rec.id);
    this.actionError.set('');
    try {
      await this.teamService.reviewRecommendation(this.teamId, rec.id, payload);
      await this.load();
      if (
        (payload.action === 'accept' || payload.action === 'override') &&
        payload.api_key_id != null
      ) {
        this.keysChanged.emit();
      }
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
      // No "Syntax error" bomb in place of a diagram that does not parse.
      // `dark` keeps node text/fills readable on the app's dark theme; `neutral`
      // matches light. Re-initialize whenever we paint so a theme toggle sticks.
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: this.theme.isDark() ? 'dark' : 'neutral',
        suppressErrorRendering: true,
      });
      // One at a time: a diagram that still fails to parse keeps its source
      // visible and must not stop the others from rendering.
      const nodes = document.querySelectorAll<HTMLElement>('.workflows-tab .mermaid:not([data-processed])');
      for (const node of Array.from(nodes)) {
        try {
          await mermaid.run({ nodes: [node] });
        } catch {
          // left as source text
        }
      }
    } catch {
      // Leave <pre class="mermaid"> source visible if render fails or mermaid is unavailable.
    }
  }

  /**
   * Mermaid replaces each <pre> with an SVG and marks it processed. To switch
   * themes we restore the source from data-diagram-source and clear the flag.
   */
  private resetProcessedDiagrams(): void {
    document.querySelectorAll<HTMLElement>('.workflows-tab .mermaid[data-processed]').forEach((node) => {
      const source = node.getAttribute('data-diagram-source');
      if (source == null) return;
      node.removeAttribute('data-processed');
      // Drop Mermaid's generated id so the next run does not collide.
      node.removeAttribute('id');
      node.textContent = source;
    });
  }
}
