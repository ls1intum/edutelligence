import { TestBed } from '@angular/core/testing';

import { TeamManagementService } from '../../../../core/services/team-management.service';
import { ModelManagementService } from '../../../../core/services/model-management.service';
import {
  AiLlmCallRecommendation,
  TeamApiKey,
  TeamWorkflowsResponse,
} from '../../../../shared/models/team.model';
import { WorkflowsTabComponent } from './workflows-tab';

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    run: vi.fn().mockResolvedValue(undefined),
  },
}));

describe('WorkflowsTabComponent review actions', () => {
  const getTeamWorkflows = vi.fn();
  const reviewRecommendation = vi.fn();
  const getModels = vi.fn();

  const pending: AiLlmCallRecommendation = {
    id: 55,
    analysis_id: 3,
    team_id: 7,
    file_path: 'src/llm.py',
    start_line: 10,
    end_line: 40,
    detected_model: 'gpt-fast',
    recommended_sla: 'ux-critical',
    objective_priority: ['latency', 'quality', 'price'],
    confidence: 0.9,
    justification: 'interactive chat',
    review_status: 'pending',
    api_key_id: 12,
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
        workflows: [
          {
            id: 1,
            analysis_id: 3,
            name: 'chat',
            trigger_summary: 'user message',
            diagram_mermaid: 'flowchart TD\n  A-->B',
            sort_order: 0,
          },
        ],
        recommendations: [pending],
      },
    ],
    pending_recommendations: [pending],
  };

  const apiKeys: TeamApiKey[] = [
    {
      id: 12,
      name: 'prod-chat',
      monthly_budget_micro_cents: null,
      cloud_rpm_limit: null,
      cloud_tpm_limit: null,
      local_rpm_limit: null,
      local_tpm_limit: null,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    getTeamWorkflows.mockResolvedValue(payload);
    reviewRecommendation.mockResolvedValue({ ...pending, review_status: 'accepted' });
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
          useValue: { getTeamWorkflows, reviewRecommendation },
        },
        {
          provide: ModelManagementService,
          useValue: { getModels },
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

  it('accepts a recommendation with the stored api_key_id and objective priority', async () => {
    const component = setup();
    await component.load();
    await component.accept(pending);
    expect(reviewRecommendation).toHaveBeenCalledWith(7, 55, {
      action: 'accept',
      api_key_id: 12,
      confirmed_objective_priority: ['latency', 'quality', 'price'],
    });
  });

  it('accepts with a user-picked api key', async () => {
    const component = setup();
    await component.load();
    component.setAcceptKey(55, '12');
    await component.accept({ ...pending, api_key_id: null });
    expect(reviewRecommendation).toHaveBeenCalledWith(7, 55, {
      action: 'accept',
      api_key_id: 12,
      confirmed_objective_priority: ['latency', 'quality', 'price'],
    });
  });

  it('overrides with the selected SLA and reordered priority', async () => {
    const component = setup();
    await component.load();
    component.setOverrideSla(55, 'ux-background');
    component.movePriority(55, 0, 1);
    await component.override(pending);
    expect(reviewRecommendation).toHaveBeenCalledWith(7, 55, {
      action: 'override',
      confirmed_sla: 'ux-background',
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

  it('resolves profile ratings for a detected model', async () => {
    const component = setup();
    await component.load();
    expect(component.ratingsForDetectedModel('gpt-fast')).toEqual({
      latency: 5,
      quality: 3,
      price: 4,
    });
  });
});
