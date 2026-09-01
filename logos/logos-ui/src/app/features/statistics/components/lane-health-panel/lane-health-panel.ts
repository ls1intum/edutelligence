import {
  Component,
  Input,
  OnChanges,
  SimpleChanges,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { StatisticsService, ProviderModel } from '../../services/statistics.service';
import { getLaneStateColor } from '../../statistics.constants';
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
 * startup log not parsed yet). Ollama lanes keep their "Active" line and
 * never reach here.
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

export interface LaneRow {
  laneId: string;
  lane: LaneSignalData;
  stateColor: string;
  kvColor: string | null;
  ttftColor: string | null;
  ttftLabel: string | null;
  /** Served context window, abbreviated — "111k". Null when unreported. */
  contextLabel: string | null;
  /** "2 / 11 (min. 8)" — see runningLabel(); null when the line is hidden. */
  runningLabel: string | null;
  /** Tooltip explaining the running/capacity numbers; null when none apply. */
  runningTooltip: string | null;
}

/**
 * Context window as a lane row shows it: thousands, rounded, no decimals.
 *
 * These sit in a dense row of stats where the exact token count is never the
 * point — an operator reads them to see which lane is the roomy one, and
 * "262,144" costs three times the width to say the same thing as "262k". Below
 * 1,000 there is nothing to abbreviate.
 */
export function formatContextWindow(tokens: number | null | undefined): string | null {
  if (typeof tokens !== 'number' || !Number.isFinite(tokens) || tokens <= 0) return null;
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens);
}

/** Which manual sleep/wake action a lane row offers, if any. */
export type LaneSleepAction = 'sleep' | 'wake' | null;

/**
 * Which manual sleep/wake action a lane row offers.
 *
 * Wake only on a lane that is actually asleep: vLLM's /wake_up on an awake
 * engine is a no-op at best, so the button would promise a transition that is
 * not coming. Sleep only on a lane that is awake and idle: the server first
 * drains in-flight requests (mode="wait"), so on a busy lane the click would
 * block for as long as the drain takes — the panel offers the action only
 * where it takes effect immediately. Lanes whose backend has no sleep mode
 * (Ollama reports sleep_state "unsupported", a vLLM lane that never slept
 * reports "unknown") offer neither.
 */
export function laneSleepAction(lane: LaneSignalData): LaneSleepAction {
  if (lane.sleep_state === 'sleeping') return 'wake';
  if (lane.sleep_state === 'awake' && !(lane.active_requests > 0)) return 'sleep';
  return null;
}

@Component({
  selector: 'app-stats-lane-health-panel',
  standalone: true,
  imports: [CommonModule, EmptyState],
  templateUrl: './lane-health-panel.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './lane-health-panel.scss',
})
export class LaneHealthPanel implements OnChanges {
  @Input() lanesByProvider: Record<string, Record<string, LaneSignalData>> = {};
  @Input() providerMeta: Record<string, VramProviderMeta> = {};
  @Input() selectedProvider: string | null = null;

  private statisticsService = inject(StatisticsService);

  unloadingLaneId = signal<string | null>(null);
  unloadError = signal<string | null>(null);

  // ── Sleep/wake state ─────────────────────────────────────────────────────
  sleepingLaneId = signal<string | null>(null);
  wakingLaneId = signal<string | null>(null);
  sleepWakeError = signal<string | null>(null);

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
        return {
          laneId,
          lane,
          stateColor: getLaneStateColor(lane.runtime_state),
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

  async handleUnload(laneId: string): Promise<void> {
    const pid = this.providerId;
    if (pid == null || this.unloadingLaneId() != null) return;
    this.unloadingLaneId.set(laneId);
    this.unloadError.set(null);

    try {
      await this.statisticsService.unloadLane(pid, laneId);
      this.unloadingLaneId.set(null);
    } catch (err: unknown) {
      this.unloadingLaneId.set(null);
      const e = err as { status?: number };
      if (e.status === 404 || e.status === 501 || e.status === 0) {
        this.unloadError.set('Action not available on this server yet.');
      } else {
        this.unloadError.set(`Unload of ${laneId} failed: ${this.failureDetail(err)}`);
      }
    }
  }

  async handleSleep(laneId: string): Promise<void> {
    const pid = this.providerId;
    if (pid == null || this.sleepingLaneId() != null) return;
    this.sleepingLaneId.set(laneId);
    this.sleepWakeError.set(null);

    try {
      await this.statisticsService.sleepLane(pid, laneId);
      this.sleepingLaneId.set(null);
    } catch (err: unknown) {
      this.sleepingLaneId.set(null);
      this.sleepWakeError.set(this.sleepWakeErrorText('Sleep', laneId, err));
    }
  }

  async handleWake(laneId: string): Promise<void> {
    const pid = this.providerId;
    if (pid == null || this.wakingLaneId() != null) return;
    this.wakingLaneId.set(laneId);
    this.sleepWakeError.set(null);

    try {
      await this.statisticsService.wakeLane(pid, laneId);
      this.wakingLaneId.set(null);
    } catch (err: unknown) {
      this.wakingLaneId.set(null);
      this.sleepWakeError.set(this.sleepWakeErrorText('Wake', laneId, err));
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
  }

  ngOnChanges(changes: SimpleChanges): void {
    // The provider dropdown lives outside this component: when it moves, the
    // open picker still holds the previous provider's models and selection,
    // and submitting it would load a model onto a provider that never served it.
    if (changes['selectedProvider'] && this.pickerProviderId !== this.providerId) {
      this.closePicker();
      this.loadModels.set([]);
      this.modelsLoading.set(false);
      this.acceptedModel.set(null);
      this.acceptedLaneIds = null;
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
      }
    }
  }

  selectModel(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.selectedModel.set(value || null);
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
    try {
      await this.statisticsService.addLane(pid, model);
      this.addingLane.set(false);
      this.closePicker();
      // The orchestrator answers 202: it accepted the load and runs it in the
      // background, which for a large model is minutes. Without a word here the
      // picker just closes and the operator cannot tell the request from a no-op.
      this.acceptedModel.set(model);
      // Baseline for acceptedModelIsResolved(): the lanes the accepted
      // replica is not among yet.
      const name = this.providerName;
      this.acceptedLaneIds = new Set(Object.keys(name ? (this.lanesByProvider[name] ?? {}) : {}));
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
