import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';

import { TeamManagementService } from '../../../../core/services/team-management.service';
import { ModelManagementService } from '../../../../core/services/model-management.service';
import { ThemeService } from '../../../../core/services/theme.service';
import {
  AiLlmCallRecommendation,
  AiWorkflow,
  TeamApiKey,
  TeamWorkflowsResponse,
} from '../../../../shared/models/team.model';
import { WorkflowsTabComponent } from './workflows-tab';
import mermaid from 'mermaid';
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    run: vi.fn().mockResolvedValue(undefined),
  },
}));

describe('WorkflowsTabComponent review actions', () => {
  const getTeamWorkflows = vi.fn();
  const reviewRecommendation = vi.fn();
  const setRecommendationModel = vi.fn();
  const updateWorkflow = vi.fn();
  const updateWorkflowStep = vi.fn();
  const runWorkflowBenchmark = vi.fn();
  const proposeWorkflowTaggingPr = vi.fn();
  const setWorkflowDiagram = vi.fn();
  const reviewWorkflowDiagramProposal = vi.fn();
  const getModels = vi.fn();
  const isDark = signal(false);

  const pending: AiLlmCallRecommendation = {
    id: 55,
    analysis_id: 3,
    team_id: 7,
    file_path: 'src/llm.py',
    start_line: 10,
    end_line: 40,
    detected_model: 'gpt-fast',
    recommended_slo: 'ux-critical',
    objective_priority: ['latency', 'quality', 'price'],
    confidence: 0.9,
    justification: 'interactive chat',
    review_status: 'pending',
    api_key_id: 12,
  };

  const activeWorkflow: AiWorkflow = {
    id: 1,
    analysis_id: 3,
    name: 'chat',
    trigger_summary: 'user message',
    diagram_mermaid: 'flowchart TD\n  A-->B',
    sort_order: 0,
    status: 'active',
    tag: 'chat-flow',
    steps: [
      {
        id: 101,
        workflow_id: 1,
        name: 'reply',
        sort_order: 0,
        recommended_slo: 'ux-critical',
        confirmed_slo: null,
      },
    ],
  };

  const deprecatedWorkflow: AiWorkflow = {
    id: 2,
    analysis_id: 3,
    name: 'legacy-batch',
    diagram_mermaid: '',
    sort_order: 1,
    status: 'deprecated',
  };

  const payload: TeamWorkflowsResponse = {
    team_id: 7,
    repositories: [
      {
        id: 11,
        repo_slug: 'acme/app',
        repo_url: 'https://github.com/acme/app',
        branch: 'main',
        latest_analysis: {
          id: 3,
          status: 'succeeded',
          source: 'heuristic',
          commit_sha: 'abcdef0',
        },
        workflows: [activeWorkflow, deprecatedWorkflow],
        recommendations: [pending],
      },
    ],
    pending_recommendations: [pending],
  };

  const key = (
    id: number,
    name: string,
    default_priority: number,
    environment?: string,
  ): TeamApiKey => ({
    id,
    name,
    default_priority,
    environment,
    monthly_budget_micro_cents: null,
    cloud_rpm_limit: null,
    cloud_tpm_limit: null,
    local_rpm_limit: null,
    local_tpm_limit: null,
  });
  const apiKeys: TeamApiKey[] = [
    key(3, 'staging', 5, 'staging'),
    key(12, 'prod-chat', 10, 'production'),
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    isDark.set(false);
    // A copy per load: the component updates recommendations in place.
    getTeamWorkflows.mockImplementation(async () => structuredClone(payload));
    reviewRecommendation.mockResolvedValue({ ...pending, review_status: 'accepted' });
    updateWorkflow.mockResolvedValue({ ...activeWorkflow, status: 'deprecated' });
    updateWorkflowStep.mockResolvedValue({
      ...activeWorkflow.steps![0],
      confirmed_slo: 'ux-critical',
    });
    runWorkflowBenchmark.mockResolvedValue({
      id: 9,
      workflow_id: 1,
      team_id: 7,
      candidate_model: 'gpt-fast',
      status: 'succeeded',
      sample_size: 50,
      historic_metrics: {
        sample_count: 12,
        p50_latency_ms: 100,
        p95_latency_ms: 220,
        models_seen: ['gpt-fast'],
      },
      candidate_metrics: {
        candidate_model: 'gpt-fast',
        sample_count: 4,
        p50_latency_ms: 80,
        p95_latency_ms: 150,
      },
    });
    proposeWorkflowTaggingPr.mockResolvedValue({
      agent_session_id: 42,
      workflow_id: 1,
      team_repository_id: 11,
      repo_slug: 'acme/app',
      status: 'queued',
      open_pull_request: true,
      no_push: false,
      message: 'Tagging pull-request session queued',
    });
    getModels.mockResolvedValue([
      {
        id: 1,
        name: 'gpt-fast',
        description: null,
        tags: null,
        aliases: null,
        weight_latency: null,
        weight_accuracy: null,
        weight_cost: null,
        weight_quality: null,
        profile_ratings: { latency: 5, quality: 3, price: 4 },
      },
    ]);
    TestBed.configureTestingModule({
      providers: [
        {
          provide: TeamManagementService,
          useValue: {
            getTeamWorkflows,
            reviewRecommendation,
            setRecommendationModel,
            updateWorkflow,
            updateWorkflowStep,
            runWorkflowBenchmark,
            proposeWorkflowTaggingPr,
            setWorkflowDiagram,
            reviewWorkflowDiagramProposal,
          },
        },
        {
          provide: ModelManagementService,
          useValue: { getModels },
        },
        {
          provide: ThemeService,
          useValue: { isDark, toggle: vi.fn() },
        },
      ],
    });
  });

  function setup(): WorkflowsTabComponent {
    const component = TestBed.runInInjectionContext(() => new WorkflowsTabComponent());
    component.teamId = 7;
    component.canEdit = true;
    component.apiKeys = apiKeys;
    return component;
  }

  it('loads workflows for the team', async () => {
    const component = setup();
    await component.load();
    expect(getTeamWorkflows).toHaveBeenCalledWith(7);
    expect(component.pendingRecs()).toEqual([pending]);
  });

  it('shows only active workflows by default and includes deprecated when toggled', async () => {
    const component = setup();
    await component.load();
    const repo = component.data()!.repositories[0];
    expect(component.workflowsForRepo(repo).map((w) => w.id)).toEqual([1]);
    component.showDeprecatedIgnored.set(true);
    expect(component.workflowsForRepo(repo).map((w) => w.id)).toEqual([1, 2]);
  });

  it('normalises workflow status helpers', () => {
    const component = setup();
    expect(component.workflowStatus({ ...activeWorkflow, status: 'active' })).toBe('active');
    expect(component.workflowStatus({ ...deprecatedWorkflow })).toBe('deprecated');
    expect(component.workflowStatus({ ...activeWorkflow, status: undefined as never })).toBe('active');
    expect(component.isActiveWorkflow(deprecatedWorkflow)).toBe(false);
  });

  it('accepts with the highest-priority key and the objective priority by default', async () => {
    const component = setup();
    await component.load();
    await component.accept(pending);
    expect(reviewRecommendation).toHaveBeenCalledWith(7, 55, {
      action: 'accept',
      api_key_id: 12,
      confirmed_objective_priority: ['latency', 'quality', 'price'],
    });
  });

  it('applies the one key picked for the whole tab, or none', async () => {
    const component = setup();
    await component.load();
    component.setReviewKey('3');
    await component.accept({ ...pending, api_key_id: null });
    expect(reviewRecommendation).toHaveBeenLastCalledWith(7, 55, {
      action: 'accept',
      api_key_id: 3,
      confirmed_objective_priority: ['latency', 'quality', 'price'],
    });

    component.setReviewKey('');
    await component.accept(pending);
    expect(reviewRecommendation).toHaveBeenLastCalledWith(7, 55, {
      action: 'accept',
      no_api_key: true,
      confirmed_objective_priority: ['latency', 'quality', 'price'],
    });
  });

  it('keeps the default key once a review has used it, even when priorities change', async () => {
    const component = setup();
    await component.load();
    await component.accept(pending);
    expect(reviewRecommendation).toHaveBeenLastCalledWith(
      7,
      55,
      expect.objectContaining({ api_key_id: 12 }),
    );

    // The review dropped prod-chat's priority below staging; the key refresh
    // must not move the next review to staging.
    component.apiKeys = [key(3, 'staging', 5, 'staging'), key(12, 'prod-chat', 1, 'production')];
    expect(component.reviewKeyValue()).toBe(12);
    await component.accept(pending);
    expect(reviewRecommendation).toHaveBeenLastCalledWith(
      7,
      55,
      expect.objectContaining({ api_key_id: 12 }),
    );
  });

  it('prefers a production key when priorities tie', () => {
    const component = setup();
    component.apiKeys = [key(4, 'dev', 10, 'development'), key(9, 'live', 10, 'production')];
    expect(component.reviewKeyValue()).toBe(9);
    component.apiKeys = [];
    expect(component.reviewKeyValue()).toBe('');
  });

  it('saves a model the owner picks and offers the known models', async () => {
    const component = setup();
    await component.load();
    setRecommendationModel.mockResolvedValue({ ...pending, detected_model: null });
    expect(component.modelOptions({ ...pending, detected_model: 'custom-x' })).toEqual([
      'custom-x',
      'gpt-fast',
    ]);

    await component.setModel(component.pendingRecs()[0], 'gpt-fast');
    expect(setRecommendationModel).not.toHaveBeenCalled(); // unchanged

    await component.setModel(component.pendingRecs()[0], '');
    expect(setRecommendationModel).toHaveBeenCalledWith(7, 55, null);
    expect(component.pendingRecs()[0].detected_model).toBeNull();
    expect(component.data()!.repositories[0].recommendations[0].detected_model).toBeNull();
  });

  it('quotes diagram labels before Mermaid sees them', () => {
    const component = setup();
    expect(
      component.diagramSource({
        id: 1,
        name: 'chat',
        diagram_mermaid: 'flowchart TD\n  A --> J[Title LLM (deferred)]',
        status: 'active',
        analysis_id: 3,
        sort_order: 0,
      }),
    ).toBe('flowchart TD\n  A --> J["Title LLM (deferred)"]');
  });

  it('overrides with the selected SLO and reordered priority', async () => {
    const component = setup();
    await component.load();
    component.setOverrideSlo(55, 'ux-background');
    component.movePriority(55, 0, 1);
    await component.override(pending);
    expect(reviewRecommendation).toHaveBeenCalledWith(7, 55, {
      action: 'override',
      confirmed_slo: 'ux-background',
      confirmed_objective_priority: ['quality', 'latency', 'price'],
      api_key_id: 12,
    });
  });

  it('rejects a recommendation', async () => {
    const component = setup();
    await component.load();
    await component.reject(pending);
    expect(reviewRecommendation).toHaveBeenCalledWith(7, 55, { action: 'reject' });
  });

  it('saves an edited diagram and reviews an agent proposal', async () => {
    const component = setup();
    await component.load();
    const wf = component.workflowsForRepo(component.data()!.repositories[0])[0];
    setWorkflowDiagram.mockResolvedValue({
      ...wf,
      diagram_mermaid: 'flowchart TD\n  Owner-->Edit',
      diagram_set_by_owner: true,
      proposed_diagram_mermaid: null,
    });
    component.startEditDiagram(wf);
    component.setDiagramDraft(wf.id, 'flowchart TD\n  Owner-->Edit');
    await component.saveDiagram(wf);
    expect(setWorkflowDiagram).toHaveBeenCalledWith(7, 1, 'flowchart TD\n  Owner-->Edit');
    expect(component.isEditingDiagram(wf)).toBe(false);
    expect(component.workflowsForRepo(component.data()!.repositories[0])[0].diagram_set_by_owner).toBe(
      true,
    );

    const withProposal = {
      ...wf,
      diagram_mermaid: 'flowchart TD\n  Owner-->Edit',
      diagram_set_by_owner: true,
      proposed_diagram_mermaid: 'flowchart TD\n  Agent-->New',
    };
    component.data.update((d) => {
      if (!d) return d;
      d.repositories[0].workflows[0] = withProposal;
      return { ...d };
    });
    reviewWorkflowDiagramProposal.mockResolvedValue({
      ...withProposal,
      diagram_mermaid: 'flowchart TD\n  Agent-->New',
      diagram_set_by_owner: false,
      proposed_diagram_mermaid: null,
    });
    await component.reviewDiagramProposal(withProposal, 'accept');
    expect(reviewWorkflowDiagramProposal).toHaveBeenCalledWith(7, 1, 'accept');
    expect(
      component.workflowsForRepo(component.data()!.repositories[0])[0].proposed_diagram_mermaid,
    ).toBeNull();
  });

  it('re-renders diagrams when leaving or switching the diagram editor', async () => {
    const component = setup();
    await component.load();
    const [first] = component.workflowsForRepo(component.data()!.repositories[0]);
    component['diagramsDirty'] = false;
    component.startEditDiagram(first);
    expect(component['diagramsDirty']).toBe(true);
    component['diagramsDirty'] = false;
    component.cancelEditDiagram();
    expect(component['diagramsDirty']).toBe(true);
  });

  it('resolves profile ratings for a detected model', async () => {
    const component = setup();
    await component.load();
    expect(component.ratingsForDetectedModel('gpt-fast')).toEqual({
      latency: 5,
      quality: 3,
      price: 4,
    });
  });

  it('deprecates and restores a workflow', async () => {
    const component = setup();
    await component.load();
    await component.setWorkflowStatus(activeWorkflow, 'deprecated');
    expect(updateWorkflow).toHaveBeenCalledWith(7, 1, { status: 'deprecated' });
    await component.setWorkflowStatus(deprecatedWorkflow, 'active');
    expect(updateWorkflow).toHaveBeenCalledWith(7, 2, { status: 'active' });
  });

  it('soft-deletes a workflow after confirmation', async () => {
    const component = setup();
    await component.load();
    component.askDeleteWorkflow(activeWorkflow);
    expect(component.deleteTarget()?.id).toBe(1);
    await component.confirmDeleteWorkflow();
    expect(updateWorkflow).toHaveBeenCalledWith(7, 1, { deleted: true });
    expect(component.deleteTarget()).toBeNull();
  });

  it('confirms a step SLO', async () => {
    const component = setup();
    await component.load();
    const step = component.data()!.repositories[0].workflows[0].steps![0];
    await component.confirmStepSlo(step);
    expect(updateWorkflowStep).toHaveBeenCalledWith(7, 101, { confirmed_slo: 'ux-critical' });
    expect(component.data()!.repositories[0].workflows[0].steps![0].confirmed_slo).toBe('ux-critical');
  });

  it('runs a workflow benchmark against a candidate model', async () => {
    const component = setup();
    await component.load();
    component.toggleBenchmark(activeWorkflow);
    component.benchmarkCandidate.set('gpt-fast');
    await component.runBenchmark(activeWorkflow);
    expect(runWorkflowBenchmark).toHaveBeenCalledWith(7, 1, { candidate_model: 'gpt-fast' });
    expect(component.benchmarkResult()?.historic_metrics?.sample_count).toBe(12);
  });

  it('drops a benchmark result once the panel moved to another workflow', async () => {
    const component = setup();
    await component.load();
    let resolve!: (value: unknown) => void;
    runWorkflowBenchmark.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    component.toggleBenchmark(activeWorkflow);
    component.benchmarkCandidate.set('gpt-fast');
    const pendingRun = component.runBenchmark(activeWorkflow);
    component.toggleBenchmark(deprecatedWorkflow);
    resolve({ id: 1, workflow_id: 1, historic_metrics: { sample_count: 3 } });
    await pendingRun;
    expect(component.benchmarkOpenId()).toBe(deprecatedWorkflow.id);
    expect(component.benchmarkResult()).toBeNull();
  });

  it('renders the diagrams the lifecycle filter reveals', () => {
    const component = setup();
    const internals = component as unknown as { renderDiagrams: () => Promise<void> };
    const render = vi.spyOn(internals, 'renderDiagrams').mockResolvedValue(undefined);
    component.setShowDeprecatedIgnored(true);
    component.ngAfterViewChecked();
    expect(component.showDeprecatedIgnored()).toBe(true);
    expect(render).toHaveBeenCalledTimes(1);
  });

  it('proposes a tagging pull request only when allowed to', async () => {
    const component = setup();
    await component.load();
    await component.proposeTaggingPr(activeWorkflow);
    expect(proposeWorkflowTaggingPr).not.toHaveBeenCalled();

    component.canProposeTaggingPr = true;
    await component.proposeTaggingPr(activeWorkflow);
    expect(proposeWorkflowTaggingPr).toHaveBeenCalledWith(7, 1);
    expect(component.actionInfo()).toContain('Tagging');
  });

  it('initializes Mermaid with the dark theme when Logos is dark', async () => {
    isDark.set(true);
    const component = setup();
    await component.load();
    component['diagramsDirty'] = true;
    await component['renderDiagrams']();
    expect(mermaid.initialize).toHaveBeenCalledWith(
      expect.objectContaining({ theme: 'dark' }),
    );

    isDark.set(false);
    await component['renderDiagrams']();
    expect(mermaid.initialize).toHaveBeenCalledWith(
      expect.objectContaining({ theme: 'neutral' }),
    );
  });
});
