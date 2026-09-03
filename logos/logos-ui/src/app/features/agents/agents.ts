import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AgentService } from '../../core/services/agent.service';
import {
  AgentCapacity,
  AgentControls,
  AgentRunnerMode,
  AgentEvent,
  AgentModels,
  AgentSession,
  AgentSessionStatus,
  AgentTriggers,
  AgentWorkspace,
  isActive,
} from '../../shared/models/agent.model';
import { SelectComponent, AppSelectOption } from '../../shared/components/select/select';

/** How often the list and the open session are refreshed while work is live. */
const POLL_MS = 4000;

@Component({
  selector: 'app-agents',
  standalone: true,
  imports: [CommonModule, FormsModule, SelectComponent],
  templateUrl: './agents.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './agents.scss',
})
export class Agents implements OnInit {
  private agentService = inject(AgentService);
  private destroyRef = inject(DestroyRef);

  /** The template binds a numeric workspace id to the select's string value. */
  readonly String = String;

  // ── data ─────────────────────────────────────────────────────────────────
  sessions = signal<AgentSession[]>([]);
  workspaces = signal<AgentWorkspace[]>([]);
  capacity = signal<AgentCapacity | null>(null);
  models = signal<AgentModels | null>(null);
  triggers = signal<AgentTriggers | null>(null);
  controls = signal<AgentControls | null>(null);
  controlBusy = signal(false);
  loading = signal(true);
  error = signal<string | null>(null);

  // ── selected session ─────────────────────────────────────────────────────
  selectedId = signal<number | null>(null);
  events = signal<AgentEvent[]>([]);
  private lastEventId = 0;

  selected = computed(() => {
    const id = this.selectedId();
    return id === null ? null : (this.sessions().find((s) => s.id === id) ?? null);
  });

  // ── new-session form ─────────────────────────────────────────────────────
  showForm = signal(false);
  formWorkspaceId = signal<number | null>(null);
  formTask = signal('');
  formModel = signal<string | null>(null);
  formOpenPr = signal(true);
  formDeploy = signal(false);
  formScreenshots = signal('');
  submitting = signal(false);
  formError = signal<string | null>(null);

  newWorkspaceName = signal('');
  pauseReason = signal('');
  /** What is typed in the limit field, until it is applied. */
  limitDraft = signal('');

  /**
   * What the slider stands at: the value being dragged if there is one,
   * otherwise the limit in force — the override, or the configured value
   * when nothing overrides it.
   */
  readonly limitShown = computed(() => {
    const draft = this.limitDraft().trim();
    if (draft !== '' && Number.isFinite(Number(draft))) return Number(draft);
    const state = this.controls();
    return state?.max_parallel_override ?? state?.max_parallel_configured ?? 0;
  });

  /**
   * How far the slider goes. The configured value is the normal working
   * point, so the scale reaches past it without running to the schema's
   * hundred, which no deployment has the capacity for.
   */
  readonly limitCeiling = computed(() => {
    const state = this.controls();
    const configured = state?.max_parallel_configured ?? 10;
    // Never below what is actually set: a stored override of 80 against a
    // scale that stops at 20 would show 80 in the label, clamp the control
    // to 20, and lower the limit on the first touch of it.
    const inForce = Math.max(state?.max_parallel_override ?? 0, this.limitShown());
    return Math.min(100, Math.max(20, configured * 2, inForce));
  });
  creatingWorkspace = signal(false);

  readonly workspaceOptions = computed<AppSelectOption[]>(() =>
    this.workspaces().map((w) => ({
      value: String(w.id),
      // Surfacing occupancy here explains why a queued session is not starting:
      // one workspace runs one session at a time.
      label: w.active_sessions > 0 ? `${w.name} (busy)` : w.name,
    })),
  );

  /**
   * Only locally served models are offered: agent work runs on capacity the
   * platform already pays for, never on cloud tokens. The runner refuses
   * anything else anyway, so offering more would only invite a rejection.
   */
  readonly modelOptions = computed<AppSelectOption[]>(() =>
    (this.models()?.models ?? []).map((name) => ({ value: name, label: name })),
  );

  readonly modelPlaceholder = computed(() => {
    const models = this.models();
    if (!models) return 'Runner default';
    if (models.default) return `${models.default} (runner default)`;
    return 'Pick a model';
  });

  readonly canSubmit = computed(
    () => this.formWorkspaceId() !== null && this.formTask().trim().length >= 8,
  );

  // ── grouped view ─────────────────────────────────────────────────────────
  activeSessions = computed(() => this.sessions().filter((s) => isActive(s.status)));
  finishedSessions = computed(() => this.sessions().filter((s) => !isActive(s.status)));

  loadPercent = computed(() => Math.round((this.capacity()?.load ?? 0) * 100));

  /**
   * The session occupying each workspace, by workspace id.
   *
   * A workspace runs one session at a time — that is what makes the parallel
   * ceiling a count of workspaces — so the list can say which one rather
   * than only that it is taken.
   */
  private readonly occupants = computed(() => {
    const byWorkspace = new Map<number, AgentSession>();
    for (const session of this.activeSessions()) {
      if (!byWorkspace.has(session.workspace_id)) byWorkspace.set(session.workspace_id, session);
    }
    return byWorkspace;
  });

  occupantOf(workspace: AgentWorkspace): AgentSession | undefined {
    return this.occupants().get(workspace.id);
  }

  // ── lifecycle ────────────────────────────────────────────────────────────
  async ngOnInit(): Promise<void> {
    await this.refresh();
    const timer = setInterval(() => void this.tick(), POLL_MS);
    this.destroyRef.onDestroy(() => {
      clearInterval(timer);
      this.stopStream();
      this.resetScreenshots();
    });
  }

  private async tick(): Promise<void> {
    // Only poll while something can change; a page left open on a finished
    // session should not keep the runner busy answering.
    if (this.activeSessions().length === 0 && this.selectedId() === null) {
      await this.loadCapacity();
      return;
    }
    await this.refresh({ quiet: true });
  }

  async refresh(options: { quiet?: boolean } = {}): Promise<void> {
    if (!options.quiet) this.loading.set(true);
    try {
      const [sessions, workspaces] = await Promise.all([
        this.agentService.getSessions(),
        this.agentService.getWorkspaces(),
      ]);
      this.sessions.set(sessions);
      this.workspaces.set(workspaces);
      this.error.set(null);
      if (this.formWorkspaceId() === null && workspaces.length > 0) {
        this.formWorkspaceId.set(workspaces[0].id);
      }
      await this.loadCapacity();
      if (!options.quiet) await this.loadModelsAndTriggers();
      if (this.selectedId() !== null) await this.loadEvents();
    } catch {
      this.error.set('Could not reach the agent runner.');
    } finally {
      this.loading.set(false);
    }
  }

  private async loadCapacity(): Promise<void> {
    try {
      this.capacity.set(await this.agentService.getCapacity());
    } catch {
      this.capacity.set(null);
    }
    // Read with the capacity, not with the list: an operator who paused the
    // runner wants to see it paused on the next tick, not on the next
    // manual refresh.
    try {
      const state = await this.agentService.getControls();
      this.controls.set(state);
      if (!this.controlBusy()) {
        this.limitDraft.set(String(state.max_parallel_override ?? ''));
        this.pauseReason.set(state.mode_reason);
      }
    } catch {
      this.controls.set(null);
    }
  }

  /**
   * Run, drain, or pause. Draining starts nothing new and lets what is
   * running finish; pausing hands everything back at once.
   */
  async setMode(mode: AgentRunnerMode): Promise<void> {
    if (this.controlBusy()) return;
    this.controlBusy.set(true);
    try {
      const reason = mode === 'running' ? '' : this.pauseReason().trim();
      const state = await this.agentService.setControls({ mode, reason });
      this.controls.set(state);
      // Follow the server: after a resume the reason is gone, and a later
      // pause must not silently send the old one again.
      this.pauseReason.set(state.mode_reason);
      await this.refresh({ quiet: true });
    } catch (err: unknown) {
      this.error.set(this.messageOf(err, 'Could not change the runner controls.'));
    } finally {
      this.controlBusy.set(false);
    }
  }

  readonly modeLabel = computed(() => {
    const mode = this.controls()?.mode;
    if (mode === 'paused') return 'Paused — everything handed back';
    if (mode === 'draining') return 'Draining — no new sessions';
    return 'Running';
  });

  /**
   * Change how many sessions may run at once, from now on.
   *
   * Called when the field is left or Enter is pressed, never on each
   * keystroke: submitting per character disables the input mid-number, so
   * "25" could not be typed at all.
   */
  async applyLimit(value: string): Promise<void> {
    if (this.controlBusy()) return;
    const trimmed = value.trim();
    let body: { max_parallel?: number; clear_max_parallel?: boolean };
    if (trimmed === '') {
      body = { clear_max_parallel: true };
    } else {
      const parsed = Number(trimmed);
      if (!Number.isFinite(parsed)) {
        // Nothing to send: an unparseable field is a typo, not an
        // instruction, and null would silently mean "no change".
        this.limitDraft.set(String(this.controls()?.max_parallel_override ?? ''));
        return;
      }
      body = { max_parallel: Math.max(0, Math.min(100, Math.round(parsed))) };
    }
    this.controlBusy.set(true);
    try {
      const state = await this.agentService.setControls(body);
      this.controls.set(state);
      this.limitDraft.set(String(state.max_parallel_override ?? ''));
      await this.refresh({ quiet: true });
    } catch (err: unknown) {
      this.error.set(this.messageOf(err, 'Could not change the session limit.'));
    } finally {
      this.controlBusy.set(false);
    }
  }

  private async loadModelsAndTriggers(): Promise<void> {
    // Both are small and change rarely, so they are read with the list
    // rather than on every poll.
    try {
      this.models.set(await this.agentService.getModels());
    } catch {
      this.models.set(null);
    }
    try {
      this.triggers.set(await this.agentService.getTriggers());
    } catch {
      this.triggers.set(null);
    }
  }

  // ── session selection ────────────────────────────────────────────────────
  async select(session: AgentSession): Promise<void> {
    if (this.selectedId() === session.id) {
      this.selectedId.set(null);
      this.events.set([]);
      this.stopStream();
      this.resetScreenshots();
      return;
    }
    this.selectedId.set(session.id);
    this.events.set([]);
    this.lastEventId = 0;
    this.stopStream();
    this.resetScreenshots();
    await this.loadEvents();
    // The load is asynchronous, and the selection may have moved on while
    // it ran. Opening the stream anyway would leave a connection nobody
    // holds the handle to — untracked, unabortable, and read by the server
    // for as long as it stays open.
    if (this.selectedId() !== session.id) return;
    this.startStream(session.id);
  }

  /**
   * Follow an open session's output as it is written.
   *
   * The four-second poll is what made a working session look like a stalled
   * one: the agent prints a line and it appears whenever the next poll
   * happens to run. The stream carries each event as the runner writes it;
   * polling stays as the fallback, so a proxy that will not hold a long
   * response degrades to what it did before rather than to nothing.
   */
  private startStream(sessionId: number): void {
    // Whatever was streaming stops first: two controllers in `this.stream`
    // would leave the older connection with no way to abort it.
    this.stopStream();
    const controller = new AbortController();
    this.stream = controller;
    void (async () => {
      try {
        for await (const event of this.agentService.streamEvents(
          sessionId,
          this.lastEventId,
          controller.signal,
        )) {
          if (this.selectedId() !== sessionId) return;
          if (event.id <= this.lastEventId) continue;
          this.lastEventId = event.id;
          this.events.update((existing) => [...existing, event]);
          if (event.kind === 'screenshot') void this.loadScreenshots();
        }
      } catch {
        // Aborted, refused, or dropped: the poll keeps the page correct, so
        // there is nothing to report and nothing to retry here.
      } finally {
        if (this.stream === controller) this.stream = null;
      }
    })();
  }

  private stopStream(): void {
    this.stream?.abort();
    this.stream = null;
  }

  private stream: AbortController | null = null;
  retrying = signal<number | null>(null);
  moving = signal<number | null>(null);

  /**
   * The queue, in the order the runner will work through it.
   *
   * Not the order the list arrives in: sessions come newest-first, and the
   * scheduler takes the most urgent, oldest among equals. Showing one and
   * moving by the other would grey out the arrows on the wrong rows.
   */
  readonly queuedSessions = computed(() =>
    this.sessions()
      .filter((s) => s.status === 'queued')
      .sort(
        (a, b) =>
          b.priority - a.priority || a.created_at.localeCompare(b.created_at) || a.id - b.id,
      ),
  );

  /**
   * Move a queued session in the queue.
   *
   * Priority is derived from what a request is, which is right most of the
   * time. The rest — which review is holding up a release, which issue can
   * wait until tomorrow — is something the person watching knows and the
   * rules do not.
   */
  async move(session: AgentSession, where: 'up' | 'down' | 'first'): Promise<void> {
    if (this.moving() !== null) return;
    this.moving.set(session.id);
    try {
      await this.agentService.moveInQueue(session.id, where);
      await this.refresh({ quiet: true });
    } catch (err: unknown) {
      this.error.set(this.messageOf(err, 'Could not move that session in the queue.'));
    } finally {
      this.moving.set(null);
    }
  }

  /**
   * Queue a finished session's work again.
   *
   * A session that failed keeps its task, its workspace and — for work the
   * runner took on itself — the branch and the thread it belongs to. What
   * came from the repository is not queued a second time by the poller
   * either: the trigger counts as handled the moment a session exists for
   * it, so without this the request was simply gone.
   */
  async retry(session: AgentSession): Promise<void> {
    if (this.retrying() !== null) return;
    this.retrying.set(session.id);
    try {
      const fresh = await this.agentService.retrySession(session.id);
      await this.refresh({ quiet: true });
      // Only if the person is still looking at what they retried: opening
      // the new session over a selection they made in the meantime would
      // clear that transcript and abort its stream.
      if (this.selectedId() === session.id) await this.select(fresh);
    } catch (err: unknown) {
      this.error.set(this.messageOf(err, 'Could not queue that work again.'));
    } finally {
      this.retrying.set(null);
    }
  }

  private async loadEvents(): Promise<void> {
    const id = this.selectedId();
    if (id === null) return;
    try {
      const answer = await this.agentService.getEvents(id, this.lastEventId);
      // Filtered against the cursor as it is *now*, not as it was when the
      // request went out: the stream appends while this is in flight, and
      // an event both of them saw would otherwise be shown twice.
      const fresh = answer.filter((event) => event.id > this.lastEventId);
      if (this.selectedId() !== id) return;
      if (fresh.length > 0) {
        this.lastEventId = fresh[fresh.length - 1].id;
        this.events.update((existing) => [...existing, ...fresh]);
      }
      // Outside the fresh-events branch on purpose: screenshot events are
      // normally the final ones, so once polling has consumed them a failed
      // blob fetch would never see fresh events again — only this per-poll
      // call retries it. Unresolved names are skipped, so steady state costs
      // nothing but the check.
      void this.loadScreenshots();
    } catch {
      /* transient; the next poll retries */
    }
  }

  /** Flatten log events into displayable lines, newest last. */
  logLines = computed(() => {
    const lines: string[] = [];
    for (const event of this.events()) {
      if (event.kind === 'log') {
        const payload = event.payload as { lines?: string[] };
        lines.push(...(payload.lines ?? []));
      } else if (event.kind === 'capacity') {
        const payload = event.payload as { decision?: string; reason?: string };
        lines.push(`— runner ${payload.decision}: ${payload.reason}`);
      } else if (event.kind === 'error') {
        const payload = event.payload as { message?: string };
        lines.push(`!! ${payload.message ?? 'error'}`);
      } else if (event.kind === 'deploy') {
        const payload = event.payload as { status?: string; reason?: string; error?: string };
        lines.push(`— deploy ${payload.status}${payload.reason ? `: ${payload.reason}` : ''}`);
      }
    }
    return lines;
  });

  /**
   * The transcript as one string. Joined here rather than looped in the
   * template so the `<pre>` keeps exact whitespace — a control-flow block
   * inside it would introduce its own.
   */
  transcriptText = computed(() => this.logLines().join('\n'));

  /** The shots captured so far, with the object URLs their blobs are shown as. */
  screenshots = signal<Array<{ name: string; url: string }>>([]);
  /** Object URL per screenshot name; revoked when the shot leaves the view. */
  private screenshotUrls = new Map<string, string>();
  /** Names whose blob fetch is in flight, so a poll does not double-fetch. */
  private screenshotInFlight = new Set<string>();

  private screenshotNames = computed(() =>
    this.events()
      .filter((e) => e.kind === 'screenshot')
      .map((e) => String((e.payload as { name?: string }).name ?? ''))
      .filter((n) => n.length > 0),
  );

  /**
   * The screenshot endpoint requires a bearer token, and a native
   * `<img>`/`<a>` request would bypass the auth interceptor and receive a
   * 401. Each shot is therefore fetched through HttpClient as a blob and
   * shown via an object URL, revoked when the shot leaves the view or the
   * component is destroyed.
   */
  private async loadScreenshots(): Promise<void> {
    const id = this.selectedId();
    if (id === null) return;
    for (const name of this.screenshotNames()) {
      if (this.screenshotUrls.has(name) || this.screenshotInFlight.has(name)) continue;
      this.screenshotInFlight.add(name);
      try {
        const blob = await this.agentService.getScreenshotBlob(id, name);
        // A selection change while the fetch was in flight already reset
        // the URL state; do not adopt the blob (no object URL created).
        if (this.selectedId() !== id) return;
        this.screenshotUrls.set(name, URL.createObjectURL(blob));
        this.publishScreenshots();
      } catch {
        /* transient; the next poll retries */
      } finally {
        this.screenshotInFlight.delete(name);
      }
    }
  }

  private publishScreenshots(): void {
    this.screenshots.set(
      this.screenshotNames()
        .filter((name) => this.screenshotUrls.has(name))
        .map((name) => ({ name, url: this.screenshotUrls.get(name) as string })),
    );
  }

  private resetScreenshots(): void {
    for (const url of this.screenshotUrls.values()) URL.revokeObjectURL(url);
    this.screenshotUrls.clear();
    this.screenshots.set([]);
  }

  // ── actions ──────────────────────────────────────────────────────────────
  openForm(): void {
    this.showForm.set(true);
    this.formError.set(null);
  }

  closeForm(): void {
    this.showForm.set(false);
    this.formTask.set('');
    this.formScreenshots.set('');
    this.formError.set(null);
  }

  async createWorkspace(): Promise<void> {
    const name = this.newWorkspaceName().trim();
    if (!name) return;
    this.creatingWorkspace.set(true);
    try {
      const workspace = await this.agentService.createWorkspace(name, 'main');
      this.workspaces.update((list) => [workspace, ...list]);
      this.formWorkspaceId.set(workspace.id);
      this.newWorkspaceName.set('');
      this.formError.set(null);
    } catch (err: unknown) {
      this.formError.set(this.messageOf(err, 'Could not create the workspace.'));
    } finally {
      this.creatingWorkspace.set(false);
    }
  }

  async deleteWorkspace(workspace: AgentWorkspace): Promise<void> {
    try {
      await this.agentService.deleteWorkspace(workspace.id);
      this.workspaces.update((list) => list.filter((w) => w.id !== workspace.id));
    } catch (err: unknown) {
      this.error.set(this.messageOf(err, 'Could not delete the workspace.'));
    }
  }

  async submit(): Promise<void> {
    const workspaceId = this.formWorkspaceId();
    if (workspaceId === null || !this.canSubmit()) return;

    this.submitting.set(true);
    this.formError.set(null);
    try {
      const paths = this.formScreenshots()
        .split(/[\s,]+/)
        .map((p) => p.trim())
        .filter((p) => p.length > 0);

      const session = await this.agentService.createSession({
        workspace_id: workspaceId,
        task: this.formTask().trim(),
        // Left null when nothing was picked: the runner then uses its own
        // default, which is the single local model where there is only one.
        model: this.formModel(),
        open_pull_request: this.formOpenPr(),
        deploy_to_dev: this.formDeploy(),
        screenshot_paths: paths,
      });
      this.sessions.update((list) => [session, ...list]);
      this.closeForm();
      await this.select(session);
    } catch (err: unknown) {
      this.formError.set(this.messageOf(err, 'Could not queue the session.'));
    } finally {
      this.submitting.set(false);
    }
  }

  async cancel(session: AgentSession): Promise<void> {
    try {
      await this.agentService.cancelSession(session.id);
      await this.refresh({ quiet: true });
    } catch (err: unknown) {
      this.error.set(this.messageOf(err, 'Could not cancel the session.'));
    }
  }

  selectWorkspaceById(id: string): void {
    this.formWorkspaceId.set(Number(id));
  }

  selectModel(name: string): void {
    this.formModel.set(name || null);
  }

  /** Where a session came from, for the list. */
  originOf(session: AgentSession): string {
    if (session.trigger_kind === 'issue') return 'from an issue';
    if (session.trigger_kind === 'review') return 'from a review';
    return session.created_by;
  }

  // ── presentation helpers ─────────────────────────────────────────────────
  statusClass(status: AgentSessionStatus): string {
    return `status status--${status}`;
  }

  statusLabel(session: AgentSession): string {
    if (session.status === 'queued') {
      const capacity = this.capacity();
      // A queued session with no capacity is waiting on purpose, not stuck.
      if (capacity && !capacity.may_start) return 'queued · waiting for capacity';
    }
    if (session.status === 'finalizing') {
      // The agent is done; the runner is committing and pushing the work.
      return 'finalizing · pushing changes';
    }
    return session.status;
  }

  duration(session: AgentSession): string {
    if (!session.started_at) return '—';
    const end = session.finished_at ? new Date(session.finished_at) : new Date();
    const seconds = Math.max(0, (end.getTime() - new Date(session.started_at).getTime()) / 1000);
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  }

  taskPreview(task: string): string {
    const firstLine = task.split('\n')[0].trim();
    return firstLine.length > 110 ? `${firstLine.slice(0, 110)}…` : firstLine;
  }

  private messageOf(err: unknown, fallback: string): string {
    const detail = (err as { error?: { detail?: string } })?.error?.detail;
    return typeof detail === 'string' && detail.length > 0 ? detail : fallback;
  }
}
