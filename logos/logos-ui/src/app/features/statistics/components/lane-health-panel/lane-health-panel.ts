import {
  Component,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  computed,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { StatisticsService, ProviderModel } from '../../services/statistics.service';
import { getLaneStateColor } from '../../statistics.constants';
import { formatTokenCount } from '../../statistics.utils';
import { LaneSignalData, VramProviderMeta } from '../../statistics.models';
import { EmptyState } from '../empty-state/empty-state';

const STATE_ORDER: Record<string, number> = {
  running: 0,
  loaded: 1,
  starting: 2,
  sleeping: 3,
  cold: 4,
  stopped: 5,
  error: 6,
};

function kvBarColor(pct: number): string {
  if (pct < 50) return 'rgb(var(--color-success))';
  if (pct < 80) return 'rgb(var(--color-warning))';
  return 'rgb(var(--color-error))';
}

function ttftColor(secs: number): string {
  if (secs < 0.2) return 'rgb(var(--color-success))';
  if (secs < 0.5) return 'rgb(var(--color-warning))';
  return 'rgb(var(--color-error))';
}

/**
 * The vLLM lane's "Running" line as "a / b (min. c)":
 * - a: requests running right now (vLLM `num_requests_running`).
 * - b: current concurrency capacity — the already-running requests plus how
 *      many full-context requests fit into the free KV headroom. Request
 *      contexts are rarely full, so this floats with the workload, usually
 *      above c.
 * - c: the minimum the worker guarantees — its KV budget at full context
 *      (vLLM's startup log line "Maximum concurrency for N tokens per
 *      request"). Shown only when b actually exceeds it; at idle "0 / 8"
 *      would just restate the minimum.
 *
 * Returns null when the lane reports no running count (the line stays
 * hidden) and plain "a" while c is unknown (lane still starting up, or the
 * startup log not parsed yet).
 */
function runningLabel(
  lane: Pick<LaneSignalData, 'requests_running' | 'num_parallel'>,
  kvPct: number | null,
): string | null {
  const a = lane.requests_running;
  if (a == null) return null;
  const c = lane.num_parallel;
  if (!c || c <= 0) return String(a);
  if (kvPct == null) return `${a} / ${c}`;
  const free = Math.max(0, 1 - kvPct / 100);
  // Block rounding can push the KV fraction slightly past the token ratio,
  // so clamp b to the guaranteed minimum instead of dipping below it.
  const b = Math.max(c, a + Math.floor(c * free));
  return b > c ? `${a} / ${b} (min. ${c})` : `${a} / ${b}`;
}

/** Lane states that do not count towards a model's live replica count. */
const NOT_LIVE_STATES = new Set(['stopped', 'error']);

/**
 * Live lanes per model (keyed by the lower-cased, trimmed model name).
 *
 * Stopped and error lanes are not counted — they serve no requests — so the
 * picker's badge agrees with what the capacity planner schedules: a model
 * whose one lane is in error reads as not running, and loading it again
 * allocates it a fresh lane id rather than the broken lane's.
 */
export function countLiveLanesByModel(
  lanes: Record<string, LaneSignalData>,
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const lane of Object.values(lanes)) {
    if (NOT_LIVE_STATES.has(lane.runtime_state)) continue;
    const key = (lane.model ?? '').trim().toLowerCase();
    if (!key) continue;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

/**
 * Models the "Load lane" picker still offers.
 *
 * Every provider model is offered, loaded or not: a model that already runs
 * lanes on the node may take one more (multiple deployments of one model per
 * node are supported), and the worker's own VRAM is the final word on
 * whether the copy fits. The only model withheld is one whose load was just
 * accepted and whose lane has not shown up in the status stream yet (that
 * takes minutes) — offering it again would invite a second click on the very
 * lane the first request is still bringing up.
 */
export function filterLoadableModels(
  models: ProviderModel[],
  acceptedModel: string | null,
): ProviderModel[] {
  const key = (acceptedModel ?? '').trim().toLowerCase();
  return models.filter((m) => m.model_name && m.model_name.trim().toLowerCase() !== key);
}

/**
 * Whether the "load accepted" note can go.
 *
 * The note is keyed to the lane ids the provider reported when the load was
 * accepted, not to the model name: a model that already ran lanes keeps them
 * reporting while the accepted copy is still minutes away, and those siblings
 * must not end the note — that would re-offer the model before the lane it
 * just asked for has shown up. The note drops only when a lane of the model
 * appears under an id that was not among them: that lane is the accepted
 * replica itself, in whatever state it reports (one that arrived is served
 * by its own row now, one that landed in error is gone and may be offered
 * again).
 */
export function acceptedModelIsResolved(
  acceptedModel: string,
  acceptedLaneIds: Iterable<string>,
  lanes: Record<string, LaneSignalData>,
): boolean {
  const wanted = acceptedModel.trim().toLowerCase();
  const snapshot = new Set(acceptedLaneIds);
  return Object.entries(lanes).some(
    ([laneId, lane]) => !snapshot.has(laneId) && (lane.model ?? '').trim().toLowerCase() === wanted,
  );
}

/**
 * The state a lane is in right now. A step in progress wins over the state the
 * worker reports, because that one still names the state the lane is leaving.
 * Without a step, a planner cold mark reads as draining: the lane still looks
 * loaded, but no new requests are routed to it.
 */
export function laneDisplayState(lane: LaneSignalData): string {
  if (lane.transition) return lane.transition;
  if (lane.cold_marked) return 'draining';
  return lane.runtime_state;
}

export interface LaneRow {
  laneId: string;
  lane: LaneSignalData;
  /** laneDisplayState as the badge shows it — "FALLING ASLEEP". */
  stateLabel: string;
  stateColor: string;
  kvColor: string | null;
  ttftColor: string | null;
  ttftLabel: string | null;
  /** Served context window, abbreviated — "111.2 K". Null when unreported. */
  contextLabel: string | null;
  /** "2 / 11 (min. 8)" — see runningLabel(); null when the line is hidden. */
  runningLabel: string | null;
  /** Tooltip explaining the running/capacity numbers; null when none apply. */
  runningTooltip: string | null;
}

/**
 * Context window as a lane row shows it: abbreviated on the shared K/M/B/T
 * token scale.
 *
 * These sit in a dense row of stats where the exact token count is never the
 * point — an operator reads them to see which lane is the roomy one, and
 * "262,144" costs more width to say the same thing as "262.1 K". Below 1,000
 * there is nothing to abbreviate.
 */
export function formatContextWindow(tokens: number | null | undefined): string | null {
  if (typeof tokens !== 'number' || !Number.isFinite(tokens) || tokens <= 0) return null;
  return formatTokenCount(tokens);
}

/** Which manual sleep/drain/wake action a lane row offers, if any. */
export type LaneSleepAction = 'sleep' | 'drain' | 'wake' | null;

/**
 * Which manual sleep/drain/wake action a lane row offers.
 *
 * None while the lane is in the middle of a step (the worker is waking it,
 * putting it to sleep or stopping it) or the planner has marked it cold: each
 * button would race a command that is already running on that lane.
 *
 * Wake only on a lane that is actually asleep: vLLM's /wake_up on an awake
 * engine is a no-op at best, so the button would promise a transition that is
 * not coming. Sleep only on a lane that is awake and idle: the server first
 * drains in-flight requests (mode="wait"), so the click takes effect
 * immediately — it is offered only where that is true.
 *
 * A busy awake lane gets Drain instead of nothing: it stops new requests from
 * reaching the lane, waits for the in-flight ones to finish, and only then
 * puts the lane to sleep — or unloads it when the host cannot hold a resident
 * sleeper, or the lane's backend has no sleep mode at all. The button is
 * offered on every busy lane (sleep mode "unknown" included): the server
 * makes the sleep-versus-unload decision with the fresh snapshot, and a lane
 * that does not drain in time simply keeps serving and can be retried.
 *
 * "Busy" mirrors the strict drain's own completion condition, which waits for
 * every activity counter to read zero: active_requests (the requests Logos is
 * proxying) plus vLLM's requests_running and queue_waiting, which can hold
 * work internally. A lane with active_requests at zero but queued vLLM work
 * would otherwise get a best-effort Sleep, whose bounded wait can reach its
 * budget and drop that work — Drain is the safe choice there.
 *
 * Lanes that are awake and idle with no sleep mode (sleep mode disabled
 * reports sleep_state "unsupported", a lane that never slept reports
 * "unknown") offer neither — there is nothing to sleep and nothing to drain.
 */
export function laneSleepAction(lane: LaneSignalData): LaneSleepAction {
  if (lane.transition || lane.cold_marked) return null;
  if (lane.sleep_state === 'sleeping') return 'wake';
  if (lane.active_requests > 0 || (lane.requests_running ?? 0) > 0 || (lane.queue_waiting ?? 0) > 0) {
    return 'drain';
  }
  if (lane.sleep_state === 'awake') return 'sleep';
  return null;
}

/** The lane id of a lock on a whole worker. No worker lane has this id. */
export const WORKER_LOCK_LANE_ID = '*';

/** Identity of a lane lock: the lane id is only unique within its provider. */
export function laneLockKey(providerId: number, laneId: string): string {
  return `${providerId}/${laneId}`;
}

@Component({
  selector: 'app-stats-lane-health-panel',
  standalone: true,
  imports: [CommonModule, EmptyState],
  templateUrl: './lane-health-panel.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './lane-health-panel.scss',
})
export class LaneHealthPanel implements OnChanges, OnDestroy {
  @Input() lanesByProvider: Record<string, Record<string, LaneSignalData>> = {};
  @Input() providerMeta: Record<string, VramProviderMeta> = {};
  @Input() selectedProvider: string | null = null;

  private statisticsService = inject(StatisticsService);

  /** Lanes of the selected provider with an unload in flight; workers unload lanes in parallel. */
  unloadingLaneIds = signal<ReadonlySet<string>>(new Set());
  unloadError = signal<string | null>(null);

  // ── Sleep/drain/wake state ───────────────────────────────────────────────
  sleepingLaneId = signal<string | null>(null);
  drainingLaneId = signal<string | null>(null);
  wakingLaneId = signal<string | null>(null);
  sleepWakeError = signal<string | null>(null);

  /** True while any sleep/drain/wake of any lane is in flight. All three
   *  buttons — and all three handlers — gate on this instead of on their own
   *  signal: a status refresh can swap a draining lane's button back to an
   *  enabled Sleep, and the per-signal guard alone would let that click
   *  through under a running drain, racing the admin commands on one lane. */
  anyLaneActionInFlight = computed(
    () => this.sleepingLaneId() !== null || this.drainingLaneId() !== null || this.wakingLaneId() !== null,
  );

  // ── Lane-lock state ──────────────────────────────────────────────────────
  /** Locked lanes of every provider, keyed by laneLockKey(). */
  lockedLanes = signal<Set<string>>(new Set());
  lockingLaneId = signal<string | null>(null);
  lockError = signal<string | null>(null);
  /** Bumped by every lock toggle and provider switch; only the current toggle may settle its state. */
  private lockAttempt = 0;
  private locksRequested = false;

  // ── Load-lane state ──────────────────────────────────────────────────────
  pickerOpen = signal(false);
  modelsLoading = signal(false);
  loadModels = signal<ProviderModel[]>([]);
  selectedModel = signal<string | null>(null);
  addingLane = signal(false);
  addError = signal<string | null>(null);
  /** Model whose background load was accepted and has not shown up as a lane yet. */
  acceptedModel = signal<string | null>(null);
  /** Lane ids the provider reported when the load was accepted — the baseline
   *  acceptedModelIsResolved() checks the stream against. */
  private acceptedLaneIds: Set<string> | null = null;
  /** Fetched model lists, keyed by provider id — never shared across providers. */
  private readonly modelsByProvider = new Map<number, ProviderModel[]>();
  private readonly modelsInFlight = new Set<number>();
  /** Provider the currently visible picker state belongs to. */
  private pickerProviderId: number | null = null;

  // ── Accepted-load outcome polling ────────────────────────────────────────
  /**
   * How often to ask for the outcome of an accepted background load. The
   * load itself takes minutes; the question here is cheap and only interesting
   * because a refusal in the background is otherwise a log line.
   */
  private static readonly LOAD_STATUS_POLL_INTERVAL_MS = 2500;
  /**
   * Hard stop for the outcome poll. A manual load gets the load command
   * timeout (30 min) plus the confirmation polling of the same length that
   * follows it, so the terminal outcome — a refusal, a confirmed lane, or a
   * recorded timeout — is recorded no later than ~60 min plus lock wait
   * after dispatch. The cap must outlive that, or it stops asking while a
   * late failure is still in flight and the note hangs; well past it the
   * live outcome is gone (planner restart, entry aged out) and the poll can
   * only re-ask for the same "unknown". The lane-appearance check in
   * ngOnChanges keeps owning the note from there on.
   */
  private static readonly LOAD_STATUS_POLL_CAP_MS = 65 * 60 * 1000;
  /** Timer handle of the outcome poll; null while not polling. */
  private loadStatusPoll: ReturnType<typeof setInterval> | null = null;
  /** Provider the outcome poll belongs to — anything else is a stale poll. */
  private loadStatusPollProviderId: number | null = null;
  /** When the outcome poll must stop regardless of what it is told. */
  private loadStatusPollDeadline = 0;
  /**
   * Generation of the polling session: every start bumps it, and each request
   * captures its own at dispatch time. A response that only resolves after a
   * newer session started (a retry of the same model) belongs to the old
   * attempt — the provider/model guards cannot tell the two apart, so it is
   * dropped instead of being applied to the new attempt's note.
   */
  private loadStatusPollGeneration = 0;

  get providerName(): string | null {
    return this.selectedProvider ?? Object.keys(this.lanesByProvider)[0] ?? null;
  }

  get lanes(): LaneRow[] {
    const name = this.providerName;
    if (!name) return [];
    const lanesForProvider = this.lanesByProvider[name] ?? {};
    return Object.entries(lanesForProvider)
      .sort(([, a], [, b]) => {
        const aOrder = STATE_ORDER[a.runtime_state] ?? 99;
        const bOrder = STATE_ORDER[b.runtime_state] ?? 99;
        if (aOrder !== bOrder) return aOrder - bOrder;
        return a.model.localeCompare(b.model);
      })
      .map(([laneId, lane]) => {
        const kvPct = lane.gpu_cache_usage_percent;
        const ttft = lane.ttft_p95_seconds;
        const running = runningLabel(lane, kvPct);
        const state = laneDisplayState(lane);
        return {
          laneId,
          lane,
          stateLabel: state.replace('_', ' ').toUpperCase(),
          stateColor: getLaneStateColor(state),
          kvColor: kvPct != null ? kvBarColor(kvPct) : null,
          ttftColor: ttft != null ? ttftColor(ttft) : null,
          ttftLabel:
            ttft != null
              ? ttft < 1
                ? `${Math.round(ttft * 1000)}ms`
                : `${ttft.toFixed(2)}s`
              : null,
          contextLabel: formatContextWindow(lane.max_model_len),
          runningLabel: running,
          runningTooltip:
            running != null && lane.num_parallel != null && lane.num_parallel > 0
              ? 'Currently running / current capacity (live KV headroom). (min. N): guaranteed at full context — the worker-reported KV budget.'
              : null,
        };
      });
  }

  /** Which sleep/wake button the row offers; the rules live in laneSleepAction. */
  sleepAction(lane: LaneSignalData): LaneSleepAction {
    return laneSleepAction(lane);
  }

  /** "GPU 0-1" style placement line; null when the lane reports none. */
  gpuLabel(lane: LaneSignalData): string | null {
    const gpu = (lane.effective_gpu_devices || lane.gpu_devices || '').trim();
    return gpu ? `GPU ${gpu}` : null;
  }

  get providerId(): number | null {
    const name = this.providerName;
    return name ? (this.providerMeta[name]?.provider_id ?? null) : null;
  }

  get providerOnline(): boolean {
    const name = this.providerName;
    if (!name) return false;
    const meta = this.providerMeta[name];
    return meta?.connection_state !== 'offline' && meta?.connected !== false;
  }

  /** Lane actions need a resolved provider that is actually reachable. */
  get canUnload(): boolean {
    return this.providerId != null && this.providerOnline;
  }

  get canAdd(): boolean {
    return this.canUnload;
  }

  /** Live lane count per model for the visible provider — see countLiveLanesByModel(). */
  get liveLaneCounts(): Map<string, number> {
    const name = this.providerName;
    const lanes = name ? (this.lanesByProvider[name] ?? {}) : {};
    return countLiveLanesByModel(lanes);
  }

  /**
   * Models that may still be loaded on this provider.
   *
   * A model with live lanes stays offered — loading it adds another
   * deployment on the node. An accepted load whose lane has not shown up in
   * the status stream yet is withheld until it appears.
   */
  get loadableModels(): ProviderModel[] {
    return filterLoadableModels(this.loadModels(), this.acceptedModel());
  }

  /** Live lanes the model already runs here — "(2 lanes)", null when none. */
  laneCountLabel(modelName: string): string | null {
    const count = this.liveLaneCounts.get(modelName.trim().toLowerCase()) ?? 0;
    return count === 1 ? '(1 lane)' : count > 1 ? `(${count} lanes)` : null;
  }

  minKvPct(pct: number): number {
    return Math.min(100, pct);
  }

  /**
   * The human-readable reason out of a failed lane action.
   *
   * Three shapes reach here and none of them can be assumed. Spring wraps its
   * own refusals as `{"error": "…"}` but passes an orchestrator refusal through
   * verbatim; FastAPI renders a bare `HTTPException` as `{"detail": "…"}`; and
   * every user-facing Logos error is normalised to the OpenAI shape,
   * `{"error": {"message": "…", "type": "…"}}`, where the text sits one level
   * further down. That last one is why a refusal could surface as the literal
   * "[object Object]": `error` held an object and went straight into the
   * message. So walk the nesting instead of guessing its depth.
   */
  private failureDetail(err: unknown): string {
    const e = err as { status?: number; error?: unknown };
    return messageIn(e?.error) ?? `HTTP ${e?.status ?? 0}`;
  }

  /**
   * Monotonic attempt counters for sleep, drain and wake, one per action
   * kind. Unloads keep one attempt per lane instead (see unloadAttempts).
   *
   * (provider, lane id) is not a unique attempt identity: a lane id is
   * per-worker and can collide across workers, and an A → B → A switch
   * re-uses both the provider and the lane name for a *newer* attempt while
   * the older one is still in flight — matching a finishing attempt on that
   * pair would let it settle the newer attempt's signal and error. Every new
   * attempt and every provider switch (which abandons the in-flight attempts)
   * bumps the counter of its kind, so a settling attempt may touch the shared
   * signal and error only while its counter is still the current one: then no
   * newer attempt of the kind has started and no switch has happened since it
   * began.
   */
  private sleepAttempt = 0;
  private drainAttempt = 0;
  private wakeAttempt = 0;

  /**
   * Unload attempts in flight, keyed by laneLockKey(provider, lane). Unloads
   * run in parallel, so each lane has its own attempt: the value is the
   * attempt's number from `unloadSeq`, and a settling attempt may touch its
   * lane's spinner and the error only while the entry still holds its number
   * and the operator is still on its provider. A provider switch clears the
   * map, which abandons every attempt in flight.
   */
  private unloadAttempts = new Map<string, number>();
  private unloadSeq = 0;

  async handleUnload(laneId: string): Promise<void> {
    const pid = this.providerId;
    if (pid == null || this.unloadingLaneIds().has(laneId)) return;
    const key = laneLockKey(pid, laneId);
    const attempt = ++this.unloadSeq;
    this.unloadAttempts.set(key, attempt);
    this.setUnloading(laneId, true);
    this.unloadError.set(null);

    let failed: unknown = null;
    try {
      await this.statisticsService.unloadLane(pid, laneId);
    } catch (err: unknown) {
      failed = err;
    }
    if (this.unloadAttempts.get(key) !== attempt || this.providerId !== pid) return;
    this.unloadAttempts.delete(key);
    this.setUnloading(laneId, false);
    if (failed === null) return;
    const e = failed as { status?: number };
    if (e.status === 404 || e.status === 501 || e.status === 0) {
      this.unloadError.set('Action not available on this server yet.');
    } else {
      this.unloadError.set(`Unload of ${laneId} failed: ${this.failureDetail(failed)}`);
    }
  }

  private setUnloading(laneId: string, unloading: boolean): void {
    const next = new Set(this.unloadingLaneIds());
    if (unloading) next.add(laneId);
    else next.delete(laneId);
    this.unloadingLaneIds.set(next);
  }

  async handleSleep(laneId: string): Promise<void> {
    const pid = this.providerId;
    // Gate on any in-flight action, not just a sleep: a drain (or wake) still
    // running on any lane must not be raced by a sleep on this one.
    if (pid == null || this.anyLaneActionInFlight()) return;
    const attempt = ++this.sleepAttempt;
    this.sleepingLaneId.set(laneId);
    this.sleepWakeError.set(null);

    let failed: unknown = null;
    try {
      await this.statisticsService.sleepLane(pid, laneId);
    } catch (err: unknown) {
      failed = err;
    }
    // Same ownership rule as the attempt counters above.
    if (this.sleepAttempt === attempt) {
      this.sleepingLaneId.set(null);
      if (failed !== null) this.sleepWakeError.set(this.sleepWakeErrorText('Sleep', laneId, failed));
    }
  }

  /**
   * Drain a busy lane: the server stops routing new requests to it, waits
   * for the in-flight ones, then sleeps (or unloads) it. The click therefore
   * runs for as long as the last request does — the "Draining…" state is the
   * operator's only feedback during the wait, so it stays up until the
   * server answers. A 409 means the lane did not drain in time and kept
   * serving; the error line says so and the button simply comes back.
   */
  async handleDrain(laneId: string): Promise<void> {
    const pid = this.providerId;
    // Gate on any in-flight action, not just a drain — see handleSleep.
    if (pid == null || this.anyLaneActionInFlight()) return;
    const attempt = ++this.drainAttempt;
    this.drainingLaneId.set(laneId);
    this.sleepWakeError.set(null);

    let failed: unknown = null;
    try {
      await this.statisticsService.drainLane(pid, laneId);
    } catch (err: unknown) {
      failed = err;
    }
    // Same ownership rule as the attempt counters above.
    if (this.drainAttempt === attempt) {
      this.drainingLaneId.set(null);
      if (failed !== null) this.sleepWakeError.set(this.sleepWakeErrorText('Drain', laneId, failed));
    }
  }

  async handleWake(laneId: string): Promise<void> {
    const pid = this.providerId;
    // Gate on any in-flight action, not just a wake — see handleSleep.
    if (pid == null || this.anyLaneActionInFlight()) return;
    const attempt = ++this.wakeAttempt;
    this.wakingLaneId.set(laneId);
    this.sleepWakeError.set(null);

    let failed: unknown = null;
    try {
      await this.statisticsService.wakeLane(pid, laneId);
    } catch (err: unknown) {
      failed = err;
    }
    // Same ownership rule as the attempt counters above.
    if (this.wakeAttempt === attempt) {
      this.wakingLaneId.set(null);
      if (failed !== null) this.sleepWakeError.set(this.sleepWakeErrorText('Wake', laneId, failed));
    }
  }

  /**
   * The human-readable reason out of a failed sleep/wake.
   *
   * Same mapping as handleUnload, with one twist: a 404 here can carry the
   * orchestrator's own reason ("lane not found on this worker"), and that
   * must win over the stale-server hint. The hint only applies when the
   * status came with no body to read at all.
   */
  private sleepWakeErrorText(verb: string, laneId: string, err: unknown): string {
    const e = err as { status?: number };
    const detail = this.failureDetail(err);
    if ((e.status === 404 || e.status === 501 || e.status === 0) && detail === `HTTP ${e?.status ?? 0}`) {
      return 'Action not available on this server yet.';
    }
    return `${verb} of ${laneId} failed: ${detail}`;
  }

  // ── Load-lane handlers ───────────────────────────────────────────────────

  openPicker(): void {
    this.pickerOpen.set(true);
    this.addError.set(null);
    const pid = this.providerId;
    this.pickerProviderId = pid;
    if (pid == null) {
      this.loadModels.set([]);
      this.modelsLoading.set(false);
      return;
    }

    // Show whatever we already have for *this* provider, never another one's.
    this.loadModels.set(this.modelsByProvider.get(pid) ?? []);
    if (this.modelsByProvider.has(pid)) {
      this.modelsLoading.set(false);
      return;
    }
    if (this.modelsInFlight.has(pid)) {
      this.modelsLoading.set(true);
      return;
    }

    this.modelsInFlight.add(pid);
    this.modelsLoading.set(true);
    this.statisticsService
      .getProviderModels(pid)
      .then((models) => {
        this.modelsByProvider.set(pid, models ?? []);
        // Discard the response if the operator moved on to another provider.
        if (this.pickerProviderId === pid) this.loadModels.set(models ?? []);
      })
      .catch((err: unknown) => {
        if (this.pickerProviderId === pid) {
          this.addError.set(`Could not load models: ${this.failureDetail(err)}`);
        }
      })
      .finally(() => {
        this.modelsInFlight.delete(pid);
        if (this.pickerProviderId === pid) this.modelsLoading.set(false);
      });
  }

  closePicker(): void {
    this.pickerOpen.set(false);
    this.selectedModel.set(null);
    this.addError.set(null);
    this.pickerProviderId = null;
    // The outcome poll deliberately keeps running: the picker's Close button
    // is not the end of an accepted load. The pending note stays up, and the
    // poll is what will surface a background refusal minutes later — stopping
    // it here would let such a refusal leave the note hanging indefinitely.
    // It stops on its own when the attempt resolves, is superseded by a new
    // one, the provider changes, it outlives the cap, or the panel is gone.
  }

  ngOnChanges(changes: SimpleChanges): void {
    // The provider dropdown lives outside this component: when it moves, the
    // open picker still holds the previous provider's models and selection,
    // and submitting it would load a model onto a provider that never served it.
    if (changes['selectedProvider'] && this.pickerProviderId !== this.providerId) {
      this.closePicker();
      // closePicker() no longer stops the outcome poll on its own (a plain
      // Close must not kill it) — a provider change abandons the attempt, so
      // stop it explicitly here.
      this.stopLoadStatusPoll();
      this.loadModels.set([]);
      this.modelsLoading.set(false);
      this.acceptedModel.set(null);
      this.acceptedLaneIds = null;
      // Action feedback belongs to the worker it was reported on: an unload
      // error or a still-spinning button from worker A must not sit under
      // worker B's panel after the switch.
      this.unloadError.set(null);
      this.unloadingLaneIds.set(new Set());
      this.sleepWakeError.set(null);
      this.sleepingLaneId.set(null);
      this.drainingLaneId.set(null);
      this.wakingLaneId.set(null);
      this.lockError.set(null);
      this.lockingLaneId.set(null);
      // The in-flight calls are abandoned as well: when they settle later,
      // their counters no longer match, so they cannot touch the shared
      // signal or error of the worker the operator is on now.
      this.lockAttempt++;
      this.unloadAttempts.clear();
      this.sleepAttempt++;
      this.drainAttempt++;
      this.wakeAttempt++;
    }
    // The lane the operator asked for has arrived in the status stream — the
    // row itself now reports its state, so the pending note has nothing to
    // add. Sibling lanes of the model do not count: the note is keyed to the
    // lane ids present when the load was accepted, so it stays up until the
    // accepted replica shows up under a fresh id of its own.
    const accepted = this.acceptedModel();
    const baseline = this.acceptedLaneIds;
    if (accepted !== null && baseline !== null && changes['lanesByProvider']) {
      const name = this.providerName;
      if (
        acceptedModelIsResolved(accepted, baseline, name ? (this.lanesByProvider[name] ?? {}) : {})
      ) {
        this.acceptedModel.set(null);
        this.acceptedLaneIds = null;
        this.stopLoadStatusPoll();
      }
    }
    // Locks are written only from this panel, so they are read once and after
    // every toggle — not on each status tick, which arrives every few seconds.
    if (!this.locksRequested) {
      this.locksRequested = true;
      void this.refreshLocks();
    }
  }

  // ── Lane locks ───────────────────────────────────────────────────────────

  /** Whether the capacity planner is told to keep this lane warm. */
  isLocked(laneId: string): boolean {
    const pid = this.providerId;
    return pid != null && this.lockedLanes().has(laneLockKey(pid, laneId));
  }

  /** Whether the capacity planner is told to leave this whole worker as it is. */
  isWorkerLocked(): boolean {
    return this.isLocked(WORKER_LOCK_LANE_ID);
  }

  /**
   * Locks or unlocks the selected worker. While it is locked, the capacity
   * planner neither loads, wakes, sleeps nor unloads anything there; the
   * buttons of this panel still work.
   */
  async handleToggleWorkerLock(): Promise<void> {
    const pid = this.providerId;
    if (pid == null || this.lockingLaneId() !== null) return;
    const locked = this.isWorkerLocked();
    const attempt = ++this.lockAttempt;
    this.lockingLaneId.set(WORKER_LOCK_LANE_ID);
    this.lockError.set(null);
    try {
      if (locked) {
        await this.statisticsService.unlockLane(pid, WORKER_LOCK_LANE_ID);
      } else {
        await this.statisticsService.lockLane(pid, WORKER_LOCK_LANE_ID, null);
      }
      await this.refreshLocks();
    } catch (err: unknown) {
      if (attempt === this.lockAttempt) {
        this.lockError.set(`${locked ? 'Unlock' : 'Lock'} of the worker failed: ${this.failureDetail(err)}`);
      }
    } finally {
      if (attempt === this.lockAttempt) this.lockingLaneId.set(null);
    }
  }

  /** Bumped by every lock read; only the newest read may set the locks. */
  private lockReadSeq = 0;

  /**
   * Re-reads the locks of every provider; a failed read keeps the last known
   * set. A read that finishes after a newer one started is dropped: the first
   * read of the panel can still be in flight when a toggle re-reads, and its
   * older answer would otherwise flip the button back.
   */
  async refreshLocks(): Promise<void> {
    const seq = ++this.lockReadSeq;
    try {
      const locks = await this.statisticsService.getLaneLocks();
      if (seq !== this.lockReadSeq) return;
      this.lockedLanes.set(new Set((locks ?? []).map((l) => laneLockKey(l.provider_id, l.lane_id))));
    } catch (err: unknown) {
      if (seq !== this.lockReadSeq) return;
      this.lockError.set(`Could not read lane locks: ${this.failureDetail(err)}`);
    }
  }

  /**
   * Locks or unlocks a lane. The toggle writes the lock table only; the
   * capacity planner picks the change up on its next cycle.
   */
  async handleToggleLock(row: LaneRow): Promise<void> {
    const pid = this.providerId;
    if (pid == null || this.lockingLaneId() !== null) return;
    const locked = this.isLocked(row.laneId);
    const attempt = ++this.lockAttempt;
    this.lockingLaneId.set(row.laneId);
    this.lockError.set(null);
    try {
      if (locked) {
        await this.statisticsService.unlockLane(pid, row.laneId);
      } else {
        await this.statisticsService.lockLane(pid, row.laneId, row.lane.model);
      }
      await this.refreshLocks();
    } catch (err: unknown) {
      if (attempt === this.lockAttempt) {
        this.lockError.set(`${locked ? 'Unlock' : 'Lock'} of ${row.laneId} failed: ${this.failureDetail(err)}`);
      }
    } finally {
      if (attempt === this.lockAttempt) this.lockingLaneId.set(null);
    }
  }

  selectModel(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.selectedModel.set(value || null);
  }

  /**
   * Start asking for the outcome of an accepted background load.
   *
   * addLane's 202 only says "accepted", and the planner refuses some loads
   * after the fact — not enough VRAM for a second replica, the worker
   * rejected the command, the confirmation timed out. Until this poll existed,
   * such a refusal was a log line and the pending note stayed up forever.
   * While the note is up, the poll turns a recorded "failed" into an error
   * (and re-offers the model) and a "succeeded" is noted as well; "running"
   * and "unknown" leave everything as it is, because the lane-appearance
   * check in ngOnChanges remains the primary exit for a load that arrives.
   */
  private startLoadStatusPoll(providerId: number, model: string): void {
    this.stopLoadStatusPoll();
    this.loadStatusPollProviderId = providerId;
    this.loadStatusPollDeadline = Date.now() + LaneHealthPanel.LOAD_STATUS_POLL_CAP_MS;
    const generation = (this.loadStatusPollGeneration += 1);
    this.loadStatusPoll = setInterval(
      () => this.pollLoadStatus(providerId, model, generation),
      LaneHealthPanel.LOAD_STATUS_POLL_INTERVAL_MS
    );
  }

  private stopLoadStatusPoll(): void {
    if (this.loadStatusPoll != null) {
      clearInterval(this.loadStatusPoll);
      this.loadStatusPoll = null;
    }
    this.loadStatusPollProviderId = null;
    this.loadStatusPollDeadline = 0;
  }

  private pollLoadStatus(providerId: number, model: string, generation: number): void {
    // The note went away (lane appeared, operator acted) or the operator moved
    // to another provider — this poll is stale, whatever the next answer says.
    if (
      this.loadStatusPollProviderId !== providerId ||
      this.providerId !== providerId ||
      this.acceptedModel()?.trim().toLowerCase() !== model.trim().toLowerCase()
    ) {
      this.stopLoadStatusPoll();
      return;
    }
    if (Date.now() > this.loadStatusPollDeadline) {
      // The orchestrator has long since resolved this load; keep the note,
      // stop re-asking for an outcome that no longer exists.
      this.stopLoadStatusPoll();
      return;
    }
    this.statisticsService
      .getLaneLoadStatus(providerId, model)
      .then((outcome) => {
        // A newer session (a retry of the same model) started while this
        // request was in flight: the answer describes the old attempt, not
        // the one whose note is up now. Drop it — and keep this session's
        // timer running, since it belongs to the newer session.
        if (generation !== this.loadStatusPollGeneration) return;
        this.applyLoadStatus(outcome, model);
      })
      .catch((err: unknown) => {
        if (generation !== this.loadStatusPollGeneration) return;
        // A blip is fine — the next tick retries. 404/501 means the application server
        // predates the load_status route, where the poll can never succeed:
        // stop and fall back to the lane-appearance check.
        const e = err as { status?: number };
        if (e.status === 404 || e.status === 501) this.stopLoadStatusPoll();
      });
  }

  /**
   * Fold one load_status answer into the pending note.
   *
   * "failed" is the interesting one: the load is over, its reason is
   * recorded, so the picker comes back with the error — exactly where a
   * synchronous refusal lands — and the model is offered again. "succeeded"
   * only stops the poll: the note stays until the lane actually shows up in
   * the stream, so the model is not re-offered in the gap between the
   * planner's record and the next status push. "running"/"unknown" change
   * nothing.
   */
  private applyLoadStatus(
    outcome: { status?: string; reason?: string },
    model: string
  ): void {
    // The answer can land after the note already went away — apply nothing.
    if (this.acceptedModel()?.trim().toLowerCase() !== model.trim().toLowerCase()) {
      this.stopLoadStatusPoll();
      return;
    }
    const status = (outcome.status ?? '').trim().toLowerCase();
    if (status !== 'failed') {
      if (status === 'succeeded') this.stopLoadStatusPoll();
      return;
    }
    this.stopLoadStatusPoll();
    this.acceptedModel.set(null);
    this.acceptedLaneIds = null;
    // The picker closed with the 202; reopen it so the reason sits next to
    // the retry, like a synchronous refusal does.
    this.openPicker();
    this.addError.set(
      `Loading ${model} failed: ${outcome.reason?.trim() || 'no reason was recorded'}`
    );
  }

  async handleAddLane(): Promise<void> {
    const pid = this.providerId;
    const model = this.selectedModel();
    if (pid == null || model == null || this.addingLane()) return;
    // Guard against a provider switch between picking and submitting.
    if (this.pickerProviderId !== pid || !this.loadModels().some((m) => m.model_name === model)) {
      this.addError.set('The provider changed — reopen the picker and select a model again.');
      return;
    }
    // Second guard, in case a selection survived the list it came from: the
    // orchestrator answers 202 and loads in the background, so the only sign
    // the first load is still running is this pending model.
    if (this.acceptedModel()?.trim().toLowerCase() === model.trim().toLowerCase()) {
      this.addError.set(`${model} is already being loaded.`);
      return;
    }
    this.addingLane.set(true);
    this.addError.set(null);
    // The orchestrator starts the background load before it answers 202, so a
    // status update can report the new starting lane while this request is
    // still in flight. The resolution baseline must be the lanes as they stood
    // before the request went out: captured after the answer arrives, a fast
    // stream would already contain the accepted lane, no update could ever
    // see it as fresh, and the pending note (and the withheld model) would
    // stay up indefinitely.
    const name = this.providerName;
    const preRequestLaneIds = new Set(Object.keys(name ? (this.lanesByProvider[name] ?? {}) : {}));
    try {
      await this.statisticsService.addLane(pid, model);
      this.addingLane.set(false);
      this.closePicker();
      // The orchestrator answers 202: it accepted the load and runs it in the
      // background, which for a large model is minutes. Without a word here the
      // picker just closes and the operator cannot tell the request from a no-op.
      this.acceptedModel.set(model);
      // Baseline for acceptedModelIsResolved(): the pre-request snapshot, so
      // the accepted lane counts as fresh whatever the stream has shown since.
      this.acceptedLaneIds = preRequestLaneIds;
      // A fast stream may already have reported the accepted lane while this
      // request was in flight: ngOnChanges ran with acceptedModel still null
      // and could not resolve the note, and the next update might be minutes
      // away (the lane only changes state when the load finishes). Re-check
      // the resolution against the current stream right here, so a lane that
      // is already visible clears the note (and re-offers the model)
      // immediately instead of waiting for the next push.
      if (
        acceptedModelIsResolved(
          model,
          preRequestLaneIds,
          name ? (this.lanesByProvider[name] ?? {}) : {},
        )
      ) {
        this.acceptedModel.set(null);
        this.acceptedLaneIds = null;
      } else {
        // The note stays up — put the outcome poll behind it, so a refusal in
        // the background ends it with a reason instead of running away.
        this.startLoadStatusPoll(pid, model);
      }
    } catch (err: unknown) {
      this.addingLane.set(false);
      const e = err as { status?: number };
      if (e.status === 404 || e.status === 501 || e.status === 0) {
        this.addError.set('Action not available on this server yet.');
      } else {
        this.addError.set(`Loading ${model} failed: ${this.failureDetail(err)}`);
      }
    }
  }

  ngOnDestroy(): void {
    this.stopLoadStatusPoll();
  }
}

/**
 * First human-readable string inside an error body, whatever it is nested in.
 *
 * `message` before `error` before `detail`, so the OpenAI shape resolves to its
 * own text rather than to the object holding it. Bounded depth: an error body is
 * a few levels at most, and a cycle in one must not take the page down with it.
 */
export function messageIn(body: unknown, depth = 0): string | null {
  if (typeof body === 'string') return body.trim() || null;
  if (depth >= 4 || body === null || typeof body !== 'object') return null;
  const record = body as Record<string, unknown>;
  for (const key of ['message', 'error', 'detail']) {
    const found = messageIn(record[key], depth + 1);
    if (found) return found;
  }
  return null;
}
