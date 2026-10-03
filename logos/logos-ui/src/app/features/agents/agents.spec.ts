import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AgentService } from '../../core/services/agent.service';
import {
  ACTIVE_SESSION_STATUSES,
  AgentCapacity,
  AgentControls,
  AgentInstructions,
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
 * Both read off the same status set as the application service, so a status the runner
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
  priority: 50,
  priority_reason: null,
  environment_notes: null,
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
  instructionBodies: Record<string, unknown>[] = [];

  async getInstructions(): Promise<AgentInstructions> {
    return {
      house_rules: 'the shipped rules',
      environment_notes: 'the shipped notes',
      house_rules_default: true,
      environment_notes_default: true,
      updated_by: '',
    };
  }

  async setInstructions(body: Record<string, unknown>): Promise<AgentInstructions> {
    this.instructionBodies.push(body);
    return {
      house_rules: 'the shipped rules',
      environment_notes: 'the shipped notes',
      house_rules_default: true,
      environment_notes_default: true,
      updated_by: 'tester',
    };
  }

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

  async getControls(): Promise<AgentControls> {
    return {
      mode: 'running',
      mode_reason: '',
      paused: false,
      admits_new_sessions: true,
      max_parallel: 10,
      max_parallel_override: null,
      max_parallel_configured: 10,
      updated_by: '',
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
    vi.useRealTimers();
  });

  describe('session timings', () => {
    beforeEach(async () => {
      vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
      vi.setSystemTime(new Date('2026-09-02T10:02:09Z'));
      fixture.detectChanges();
      await component.refresh();
    });

    const timings = (): string[] =>
      Array.from(
        fixture.nativeElement.querySelectorAll('.session__timing') as NodeListOf<HTMLElement>,
      ).map((element) => element.textContent!.trim());

    it('updates queue waits and running durations every second between server polls', async () => {
      agentService.sessions = [
        makeSession({
          id: 1,
          status: 'queued',
          created_at: '2026-09-02T10:02:00Z',
          started_at: null,
        }),
        makeSession({ id: 2, status: 'running', started_at: '2026-09-02T10:02:00Z' }),
      ];
      await component.refresh();
      fixture.detectChanges();
      expect(timings()).toEqual(['Queued 9s', 'Queued 2m 0s', 'Run 9s']);
      agentService.sessionCalls = 0;

      await vi.advanceTimersByTimeAsync(1000);
      fixture.detectChanges();

      expect(timings()).toEqual(['Queued 10s', 'Queued 2m 0s', 'Run 10s']);
      expect(agentService.sessionCalls).toBe(0);
      expect(fixture.nativeElement.querySelector('.status--running')).toBeTruthy();
    });

    it.each(['succeeded', 'failed', 'cancelled'] as const)(
      'updates the finish age of a %s session while queue and runtime stay fixed',
      async (status) => {
        agentService.sessions = [makeSession({ status, finished_at: '2026-09-02T10:02:00Z' })];
        await component.refresh();
        fixture.detectChanges();
        expect(timings()).toEqual(['Queued 1m 0s', 'Run 1m 0s', 'Finished 9s ago']);
        expect(
          fixture.nativeElement.querySelector('.session__timing[title^="Finished "]'),
        ).toBeTruthy();
        agentService.sessionCalls = 0;

        await vi.advanceTimersByTimeAsync(1000);
        fixture.detectChanges();

        expect(timings()).toEqual(['Queued 1m 0s', 'Run 1m 0s', 'Finished 10s ago']);
        expect(agentService.sessionCalls).toBe(0);
      },
    );

    it('freezes the queue wait when a session is cancelled before it starts', async () => {
      const session = makeSession({
        status: 'cancelled',
        started_at: null,
        finished_at: '2026-09-02T10:01:00Z',
      });
      agentService.sessions = [session];
      await component.refresh();
      fixture.detectChanges();
      expect(timings()).toEqual(['Queued 1m 0s', 'Finished 1m 9s ago']);
      expect(component.duration(session)).toBe('—');

      await vi.advanceTimersByTimeAsync(1000);
      fixture.detectChanges();

      expect(timings()).toEqual(['Queued 1m 0s', 'Finished 1m 10s ago']);
    });

    it.each([
      ['2026-09-02T10:01:09.001Z', '59s'],
      ['2026-09-02T10:01:09Z', '1m 0s'],
      ['2026-09-02T09:02:09.001Z', '59m 59s'],
      ['2026-09-02T09:02:09Z', '1h 0m'],
      ['2026-09-02T10:02:10Z', '0s'],
      ['invalid', '—'],
    ])('formats a start at %s as %s without overflowing seconds', (started_at, expected) => {
      expect(component.duration(makeSession({ started_at }))).toBe(expected);
    });

    it('stops both local timing updates and polling when the page is destroyed', async () => {
      const session = makeSession({ status: 'running', started_at: '2026-09-02T10:02:00Z' });
      const elapsed = component.duration(session);
      fixture.destroy();
      agentService.sessionCalls = 0;
      agentService.capacityCalls = 0;

      await vi.advanceTimersByTimeAsync(5000);

      expect(component.duration(session)).toBe(elapsed);
      expect(agentService.sessionCalls).toBe(0);
      expect(agentService.capacityCalls).toBe(0);
      expect(vi.getTimerCount()).toBe(0);
    });
  });

  describe('grouping', () => {
    it('keeps a finalizing session in the active group', async () => {
      // the application server counts finalizing as active (it still occupies the
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

  describe('repository analysis sessions', () => {
    it('names the team and repository being analysed', () => {
      const analysis = makeSession({
        trigger_kind: 'analysis',
        repo_slug: 'ls1intum/hestia',
        team_name: 'hestia',
      });
      expect(component.analysisTarget(analysis)).toBe('hestia · ls1intum/hestia');
      expect(component.originOf(analysis)).toBe('repository analysis');
    });

    it('falls back to the slug once the link is gone, and stays out of other sessions', () => {
      expect(
        component.analysisTarget(
          makeSession({ trigger_kind: 'analysis', repo_slug: 'ls1intum/artemis', team_name: null }),
        ),
      ).toBe('ls1intum/artemis');
      expect(
        component.analysisTarget(
          makeSession({ trigger_kind: 'issue', repo_slug: 'ls1intum/edutelligence' }),
        ),
      ).toBeNull();
    });
  });

  describe('the standing instructions', () => {
    /**
     * Reset is a statement about one box. The other one may hold an edit
     * nobody has saved yet, and sending it along would save it behind the
     * operator's back — and refilling it from the answer would throw it
     * away on screen as well.
     */
    it("resets one half without submitting the other half's draft", async () => {
      component.houseRulesDraft.set('rules nobody saved');
      component.environmentNotesDraft.set('notes nobody saved');

      await component.resetInstructions('house_rules');

      expect(agentService.instructionBodies).toEqual([{ reset_house_rules: true }]);
      expect(component.environmentNotesDraft()).toBe('notes nobody saved');
      expect(component.houseRulesDraft()).toBe('the shipped rules');
    });

    it('saves both halves when both are being saved', async () => {
      component.houseRulesDraft.set('be brief');
      component.environmentNotesDraft.set('a container');

      await component.saveInstructions();

      expect(agentService.instructionBodies).toEqual([
        { house_rules: 'be brief', environment_notes: 'a container' },
      ]);
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
