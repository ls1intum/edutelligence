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
  AgentEvent,
  AgentSession,
  AgentSessionStatus,
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
  formOpenPr = signal(true);
  formDeploy = signal(false);
  formScreenshots = signal('');
  submitting = signal(false);
  formError = signal<string | null>(null);

  newWorkspaceName = signal('');
  creatingWorkspace = signal(false);

  readonly workspaceOptions = computed<AppSelectOption[]>(() =>
    this.workspaces().map((w) => ({
      value: String(w.id),
      // Surfacing occupancy here explains why a queued session is not starting:
      // one workspace runs one session at a time.
      label: w.active_sessions > 0 ? `${w.name} (busy)` : w.name,
    })),
  );

  readonly canSubmit = computed(
    () => this.formWorkspaceId() !== null && this.formTask().trim().length >= 8,
  );

  // ── grouped view ─────────────────────────────────────────────────────────
  activeSessions = computed(() => this.sessions().filter((s) => isActive(s.status)));
  finishedSessions = computed(() => this.sessions().filter((s) => !isActive(s.status)));

  loadPercent = computed(() => Math.round((this.capacity()?.load ?? 0) * 100));

  // ── lifecycle ────────────────────────────────────────────────────────────
  async ngOnInit(): Promise<void> {
    await this.refresh();
    const timer = setInterval(() => void this.tick(), POLL_MS);
    this.destroyRef.onDestroy(() => {
      clearInterval(timer);
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
  }

  // ── session selection ────────────────────────────────────────────────────
  async select(session: AgentSession): Promise<void> {
    if (this.selectedId() === session.id) {
      this.selectedId.set(null);
      this.events.set([]);
      this.resetScreenshots();
      return;
    }
    this.selectedId.set(session.id);
    this.events.set([]);
    this.lastEventId = 0;
    this.resetScreenshots();
    await this.loadEvents();
  }

  private async loadEvents(): Promise<void> {
    const id = this.selectedId();
    if (id === null) return;
    try {
      const fresh = await this.agentService.getEvents(id, this.lastEventId);
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
