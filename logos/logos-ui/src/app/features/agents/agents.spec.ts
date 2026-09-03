import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AgentService } from '../../core/services/agent.service';
import {
  ACTIVE_SESSION_STATUSES,
  AgentCapacity,
  AgentModels,
  AgentSession,
  AgentTriggers,
  AgentWorkspace,
  isActive,
} from '../../shared/models/agent.model';
import { Agents } from './agents';

/**
 * The agents page groups the list into "active" and "finished", and it only
 * keeps polling the runner while something in that list can still change.
 * Both read off the same status set as the backend, so a status the runner
 * treats as active but the page does not would sit under Finished — stale,
 * and no longer refreshed — until a manual reload.
 */

const makeSession = (overrides: Partial<AgentSession> = {}): AgentSession => ({
  id: 1,
  workspace_id: 1,
  workspace_name: 'feature-work',
  task: 'a task description for the agent',
  status: 'finalizing',
  model: null,
  branch_name: 'agent/feature-work/session-1',
  pr_url: null,
  created_by: 'tester',
  created_at: '2026-09-02T10:00:00Z',
  started_at: '2026-09-02T10:01:00Z',
  finished_at: null,
  exit_code: null,
  error: null,
  tokens_in: 0,
  tokens_out: 0,
  cost_usd: 0,
  screenshot_count: 0,
  trigger_kind: null,
  trigger_ref: null,
  ...overrides,
});

const CAPACITY: AgentCapacity = {
  load: 0.25,
  total_slots: 4,
  busy_slots: 1,
  sessions_running: 1,
  sessions_queued: 0,
  sessions_paused: 0,
  max_parallel: 2,
  may_start: true,
  reason: 'ok',
  models_local_only: true,
  models_detail: 'one local model',
};

class FakeAgentService {
  sessions: AgentSession[] = [];
  sessionCalls = 0;
  capacityCalls = 0;

  async getSessions(): Promise<AgentSession[]> {
    this.sessionCalls += 1;
    return this.sessions;
  }

  async getWorkspaces(): Promise<AgentWorkspace[]> {
    return [];
  }

  async getCapacity(): Promise<AgentCapacity> {
    this.capacityCalls += 1;
    return CAPACITY;
  }

  async getModels(): Promise<AgentModels> {
    return {
      models: ['local-model'],
      default: 'local-model',
      local_only: true,
      detail: 'one local model',
    };
  }

  async getTriggers(): Promise<AgentTriggers> {
    return {
      enabled: false,
      polling: false,
      account: 'LogosOSSAgent',
      poll_interval_s: 120,
      max_active_sessions: 5,
      active_sessions: 0,
      last_pass: null,
      queued_total: 0,
      last_error: '',
    };
  }
}

describe('Agents', () => {
  let fixture: ComponentFixture<Agents>;
  let component: Agents;
  let agentService: FakeAgentService;

  beforeEach(async () => {
    agentService = new FakeAgentService();
    await TestBed.configureTestingModule({
      imports: [Agents],
      providers: [{ provide: AgentService, useValue: agentService }],
    }).compileComponents();
    fixture = TestBed.createComponent(Agents);
    component = fixture.componentInstance;
    // Settle the load ngOnInit kicked off, so each test starts from the
    // state the runner actually reported.
    await component.refresh();
  });

  afterEach(() => {
    // ngOnInit opened a polling interval; dropping it here keeps the event
    // loop empty for the next test.
    fixture.destroy();
  });

  describe('grouping', () => {
    it('keeps a finalizing session in the active group', async () => {
      // The backend counts finalizing as active (it still occupies the
      // workspace); the page must too, or the row renders under Finished
      // while the runner is still pushing its work.
      expect(ACTIVE_SESSION_STATUSES).toContain('finalizing');
      expect(isActive('finalizing')).toBe(true);

      agentService.sessions = [
        makeSession({ id: 1, status: 'finalizing' }),
        makeSession({ id: 2, status: 'succeeded' }),
      ];
      await component.refresh();

      expect(component.activeSessions().map((s) => s.id)).toEqual([1]);
      expect(component.finishedSessions().map((s) => s.id)).toEqual([2]);
    });
  });

  describe('polling', () => {
    // tick() is private: the poll runs on an interval, and the tests drive
    // one tick directly instead of waiting for the timer.
    const tick = (): Promise<void> => (component as unknown as { tick(): Promise<void> }).tick();

    it('keeps refreshing while a finalizing session is the only live one', async () => {
      // With nothing selected, the page only refreshes while the active
      // group is non-empty. A finalizing-only list must count as live, or
      // the row would never leave finalizing on screen.
      agentService.sessions = [makeSession({ id: 1, status: 'finalizing' })];
      await component.refresh();
      agentService.sessionCalls = 0;

      await tick();

      expect(agentService.sessionCalls).toBeGreaterThan(0);
      expect(component.activeSessions().map((s) => s.id)).toEqual([1]);
    });

    it('drops to capacity-only once nothing is live and nothing is selected', async () => {
      // The other side of the same gate: an all-finished list with no
      // selection must not keep the runner answering session polls.
      agentService.sessions = [makeSession({ id: 1, status: 'succeeded' })];
      await component.refresh();
      agentService.sessionCalls = 0;

      await tick();

      expect(agentService.sessionCalls).toBe(0);
      expect(agentService.capacityCalls).toBeGreaterThan(0);
    });
  });
});
