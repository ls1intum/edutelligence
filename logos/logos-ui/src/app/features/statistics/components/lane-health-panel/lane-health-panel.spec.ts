import { SimpleChange } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import {
  LaneHealthPanel,
  acceptedModelIsResolved,
  countLiveLanesByModel,
  filterLoadableModels,
  formatContextWindow,
  laneSleepAction,
  messageIn,
} from './lane-health-panel';
import { LaneSignalData } from '../../statistics.models';
import { ProviderModel, StatisticsService } from '../../services/statistics.service';

/**
 * Pulling the reason out of a failed lane action.
 *
 * Three shapes reach this and none of them can be assumed: Spring wraps its own
 * refusals as `{"error": "…"}`, FastAPI renders a bare HTTPException as
 * `{"detail": "…"}`, and every user-facing Logos error is normalised to the
 * OpenAI shape, where the text sits a level further down. Reading `error` as a
 * string put that last one's *object* into the message, which is how a refusal
 * came to read "Loading Qwen/Qwen3.8-27B failed: [object Object]".
 */
describe('messageIn', () => {
  it('unwraps the OpenAI error shape', () => {
    // Captured verbatim from an orchestrator that predates the lanes/add
    // endpoint — the exact body behind the [object Object] report.
    expect(
      messageIn({ error: { message: 'Not Found', type: 'not_found_error' } }),
    ).toBe('Not Found');
  });

  it('reads a real refusal out of the same shape', () => {
    expect(
      messageIn({
        error: {
          message: 'Provider has not reported its lanes yet; try again once it has connected.',
          type: 'conflict_error',
        },
      }),
    ).toBe('Provider has not reported its lanes yet; try again once it has connected.');
  });

  it("keeps working for Spring's string-valued error", () => {
    expect(messageIn({ error: 'provider_id and lane are required' })).toBe(
      'provider_id and lane are required',
    );
  });

  it("keeps working for FastAPI's detail", () => {
    expect(messageIn({ detail: 'lane.model is required' })).toBe('lane.model is required');
  });

  it('handles a detail that itself holds the OpenAI shape', () => {
    expect(messageIn({ detail: { error: { message: 'Capacity planner not ready' } } })).toBe(
      'Capacity planner not ready',
    );
  });

  it('prefers the message over the object holding it', () => {
    // Both keys present at the same level: `message` is the text, `error` is
    // more nesting. Taking `error` first would descend past the answer.
    expect(messageIn({ message: 'the reason', error: { message: 'deeper' } })).toBe('the reason');
  });

  it('returns null when there is no text to show', () => {
    expect(messageIn(undefined)).toBeNull();
    expect(messageIn(null)).toBeNull();
    expect(messageIn({})).toBeNull();
    expect(messageIn({ error: {} })).toBeNull();
    // Whitespace is not a message — the caller falls back to the status code.
    expect(messageIn({ error: '   ' })).toBeNull();
  });

  it('gives up rather than following a cycle down', () => {
    const cyclic: Record<string, unknown> = {};
    cyclic['error'] = cyclic;
    expect(messageIn(cyclic)).toBeNull();
  });
});

/**
 * The context window a lane row shows.
 *
 * Abbreviated on the shared K/M/B/T token scale, because the row is a dense
 * line of stats read to spot the roomy lane — the exact token count is never
 * what is being asked.
 */
describe('formatContextWindow', () => {
  it('abbreviates on the token scale', () => {
    expect(formatContextWindow(262144)).toBe('262.1 K');
    expect(formatContextWindow(111200)).toBe('111.2 K');
    expect(formatContextWindow(40960)).toBe('40.9 K');
    expect(formatContextWindow(1000)).toBe('1 K');
  });

  it('leaves small windows alone', () => {
    // Nothing to abbreviate, and "0k" would be worse than the number.
    expect(formatContextWindow(999)).toBe('999');
    expect(formatContextWindow(512)).toBe('512');
  });

  it('shows nothing when the worker reported nothing', () => {
    // The orchestrator sends null for a lane it cannot derive a window for —
    // a vLLM lane started without --max-model-len and never calibrated. The
    // row then omits the badge rather than claiming a size.
    expect(formatContextWindow(null)).toBeNull();
    expect(formatContextWindow(undefined)).toBeNull();
    expect(formatContextWindow(0)).toBeNull();
    expect(formatContextWindow(-1)).toBeNull();
    expect(formatContextWindow(Number.NaN)).toBeNull();
  });
});

function lane(overrides: Partial<LaneSignalData> = {}): LaneSignalData {
  return {
    model: 'org/model-a',
    runtime_state: 'loaded',
    sleep_state: 'awake',
    gpu_devices: null,
    effective_gpu_devices: null,
    num_parallel: null,
    active_requests: 0,
    effective_vram_mb: 0,
    gpu_cache_usage_percent: null,
    ttft_p95_seconds: null,
    queue_waiting: null,
    requests_running: null,
    prefix_cache_hit_rate: null,
    mtp_acceptance_rate: null,
    max_model_len: null,
    ...overrides,
  };
}

/**
 * The Wake/Sleep buttons beside Unload.
 *
 * The buttons reach the two states the capacity planner also reaches on its
 * own, so they are offered only where they mean something: Wake on a lane
 * that is actually asleep, Sleep on one that is awake and idle. A busy lane
 * gets no Sleep button — the server would refuse it anyway, and the panel
 * would just display the refusal.
 */
describe('laneSleepAction', () => {
  it('offers Wake on a sleeping lane', () => {
    expect(laneSleepAction(lane({ sleep_state: 'sleeping' }))).toBe('wake');
  });

  it('still offers Wake while a sleeping lane reports in-flight requests', () => {
    // A sleeping lane should serve nothing; if the counters say otherwise,
    // the lane is mid-transition and waking it is still the useful action.
    expect(laneSleepAction(lane({ sleep_state: 'sleeping', active_requests: 3 }))).toBe('wake');
  });

  it('offers Sleep on an awake, idle lane', () => {
    expect(laneSleepAction(lane({ sleep_state: 'awake' }))).toBe('sleep');
  });

  it('withholds Sleep from a lane that is serving', () => {
    expect(laneSleepAction(lane({ sleep_state: 'awake', active_requests: 1 }))).toBeNull();
  });

  it('withholds both actions from a lane the backend cannot sleep', () => {
    // A lane with sleep mode disabled reports "unsupported"; a lane that
    // never slept reports "unknown" until its first transition.
    expect(laneSleepAction(lane({ sleep_state: 'unsupported' }))).toBeNull();
    expect(laneSleepAction(lane({ sleep_state: 'unknown' }))).toBeNull();
    expect(laneSleepAction(lane({ sleep_state: null }))).toBeNull();
  });
});

/**
 * Which models the "Load lane" picker still offers.
 *
 * Every provider model is offered, loaded or not: a model that already runs
 * lanes on the node may take one more (multiple deployments of one model per
 * node are supported), and the worker's own VRAM is the final word on
 * whether the copy fits. The only model withheld is one whose load was just
 * accepted — its lane takes minutes to show up in the status stream, and
 * offering it again would invite a second click on the very lane being
 * brought up.
 */
describe('lane picker loadability', () => {
  it('counts every lane except stopped and error as live', () => {
    const lanes = {
      'planner-foo': lane({ model: 'foo', runtime_state: 'running' }),
      'planner-foo-2': lane({ model: 'foo', runtime_state: 'loaded' }),
      'planner-foo-3': lane({ model: 'foo', runtime_state: 'error' }),
      'planner-bar': lane({ model: 'bar', runtime_state: 'stopped' }),
    };
    // bar's only lane is stopped: no live lanes at all, so no entry — a
    // lookup misses and the model reads as 0.
    expect(countLiveLanesByModel(lanes)).toEqual(new Map([['foo', 2]]));
  });

  it('offers every provider model with a name', () => {
    const models = [
      { model_id: 1, model_name: 'foo' },
      { model_id: 2, model_name: 'bar' },
      { model_id: 3, model_name: '' },
    ];
    expect(filterLoadableModels(models, null).map((m) => m.model_name)).toEqual(['foo', 'bar']);
  });

  it('keeps a model that already runs lanes offered — loading it adds another deployment', () => {
    // bar runs one healthy and one broken lane: the broken one holds the
    // historical id, so the planner allocates a fresh one for the next load —
    // from the picker's side the model is simply offered, like any other.
    const models = [
      { model_id: 1, model_name: 'foo' },
      { model_id: 2, model_name: 'bar' },
    ];
    const live = countLiveLanesByModel({
      'planner-bar': lane({ model: 'bar', runtime_state: 'running' }),
      'planner-bar-2': lane({ model: 'bar', runtime_state: 'error' }),
    });
    expect(live).toEqual(new Map([['bar', 1]]));
    expect(filterLoadableModels(models, null).map((m) => m.model_name)).toEqual(['foo', 'bar']);
  });

  it('withholds a model whose load was just accepted', () => {
    // The accepted lane is not in the status stream yet; offering it again
    // would double-click the very lane being brought up.
    const models = [
      { model_id: 1, model_name: 'foo' },
      { model_id: 2, model_name: 'bar' },
    ];
    expect(filterLoadableModels(models, 'bar').map((m) => m.model_name)).toEqual(['foo']);
  });

  it('matches model names case-insensitively', () => {
    const models = [
      { model_id: 1, model_name: 'Foo/Baz' },
      { model_id: 2, model_name: 'qux' },
    ];
    expect(filterLoadableModels(models, ' foo/baz ').map((m) => m.model_name)).toEqual(['qux']);
  });
});

/**
 * When the "load accepted" note goes away.
 *
 * The note is keyed to the lane ids the provider reported when the load was
 * accepted. The regression it guards: an accepted *additional* replica was
 * released the moment the picker re-read the stream, because a *sibling*
 * lane of the model satisfied "the lane has arrived" — re-offering the model
 * while the accepted copy was still minutes from showing up.
 */
describe('acceptedModelIsResolved', () => {
  const sibling = lane({ model: 'foo', runtime_state: 'running' });

  it('stays up while only sibling lanes of the model are in the stream', () => {
    // The accepted additional replica has not shown up; the pre-existing
    // lane reporting the same model does not end the note.
    const lanes = { 'planner-foo': sibling };
    expect(acceptedModelIsResolved('foo', ['planner-foo'], lanes)).toBe(false);
  });

  it('is resolved when the accepted replica shows up under a fresh id', () => {
    const lanes = {
      'planner-foo': sibling,
      'planner-foo-2': lane({ model: 'foo', runtime_state: 'starting' }),
    };
    expect(acceptedModelIsResolved('foo', ['planner-foo'], lanes)).toBe(true);
  });

  it('is resolved when the accepted replica failed into an error row', () => {
    // The replica arrived in the stream but is not serving: the note is done,
    // the row shows why, and the model may be offered for a retry.
    const lanes = {
      'planner-foo': sibling,
      'planner-foo-2': lane({ model: 'foo', runtime_state: 'error' }),
    };
    expect(acceptedModelIsResolved('foo', ['planner-foo'], lanes)).toBe(true);
  });

  it('is resolved for a first lane on an empty provider', () => {
    const lanes = { 'planner-foo': lane({ model: 'foo', runtime_state: 'starting' }) };
    expect(acceptedModelIsResolved('foo', [], lanes)).toBe(true);
  });

  it('ignores a new lane of another model', () => {
    const lanes = {
      'planner-foo': sibling,
      'planner-bar': lane({ model: 'bar', runtime_state: 'loaded' }),
    };
    expect(acceptedModelIsResolved('foo', ['planner-foo'], lanes)).toBe(false);
  });

  it('ignores a state change of a pre-existing lane', () => {
    // Same id the baseline knew, new state: the sibling woke up or dropped,
    // the accepted replica still has not shown up.
    const lanes = { 'planner-foo': lane({ model: 'foo', runtime_state: 'loaded' }) };
    expect(acceptedModelIsResolved('foo', ['planner-foo'], lanes)).toBe(false);
  });

  it('matches model names case-insensitively', () => {
    const lanes = { 'planner-foo-2': lane({ model: 'Foo', runtime_state: 'loaded' }) };
    expect(acceptedModelIsResolved(' foo ', ['planner-foo'], lanes)).toBe(true);
  });
});

/**
 * The pending note's baseline and the in-flight request.
 *
 * The orchestrator starts the background load before it answers 202, so the
 * status stream can report the new starting lane while the HTTP promise is
 * still in flight. The baseline the note checks the stream against must be
 * the lanes as they stood before the request went out: captured after the
 * answer arrives, a fast stream already contains the accepted lane, no
 * update can ever see it as fresh, and the note (and the withheld model)
 * stay up indefinitely.
 */
describe('LaneHealthPanel pending-note baseline', () => {
  let fixture: ComponentFixture<LaneHealthPanel>;
  let panel: LaneHealthPanel;
  let resolveAdd: (() => void) | undefined;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LaneHealthPanel],
      providers: [
        {
          provide: StatisticsService,
          useValue: {
            addLane: () =>
              new Promise<void>((resolve) => {
                resolveAdd = resolve;
              }),
            // The 202 starts the outcome poll, whose first tick lands 2.5 s
            // later — beyond these tests' horizon, but a slow CI must not hit
            // a stub without this method.
            getLaneLoadStatus: () => Promise.resolve({ status: 'running' }),
          },
        },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(LaneHealthPanel);
    panel = fixture.componentInstance;
    fixture.componentRef.setInput('lanesByProvider', {
      'gpu-01': { 'planner-foo': lane({ model: 'foo', runtime_state: 'running' }) },
    });
    fixture.componentRef.setInput('providerMeta', { 'gpu-01': { provider_id: 1 } });
    fixture.componentRef.setInput('selectedProvider', 'gpu-01');
    panel.loadModels.set([{ model_id: 1, model_name: 'foo' }] satisfies ProviderModel[]);
    (panel as unknown as { pickerProviderId: number | null }).pickerProviderId = 1;
    panel.selectedModel.set('foo');
    fixture.detectChanges();
  });

  /** One status-stream push: swap the input and deliver ngOnChanges, as the
   *  framework does — the test reads the signals afterwards, no re-render. */
  function pushLanes(next: Record<string, LaneSignalData>): void {
    const prev = panel.lanesByProvider;
    panel.lanesByProvider = { ...prev, 'gpu-01': next };
    panel.ngOnChanges({ lanesByProvider: new SimpleChange(prev, panel.lanesByProvider, false) });
  }

  it('resolves the note when the accepted lane arrived while the request was in flight', async () => {
    const inFlight = panel.handleAddLane();

    // A fast status update reports the new starting lane before the HTTP
    // promise settles — the stream already contains the accepted replica,
    // and ngOnChanges cannot act on it yet: acceptedModel is still null.
    pushLanes({
      'planner-foo': lane({ model: 'foo', runtime_state: 'running' }),
      'planner-foo-2': lane({ model: 'foo', runtime_state: 'starting' }),
    });

    resolveAdd?.();
    await inFlight;

    // The replica the stream has been reporting all along counts as fresh:
    // the note never needs to stay up, and the model is offered again
    // immediately — not on the next update.
    expect(panel.acceptedModel()).toBeNull();
    expect(filterLoadableModels(panel.loadModels(), panel.acceptedModel())).toEqual([
      { model_id: 1, model_name: 'foo' },
    ]);
  });

  it('keeps the note up while only sibling lanes report in flight', async () => {
    // The in-flight update touches a pre-existing lane (a sibling woke up):
    // the accepted replica is not among them, so the note must survive the
    // pre-request snapshot being the only baseline.
    const inFlight = panel.handleAddLane();
    pushLanes({ 'planner-foo': lane({ model: 'foo', runtime_state: 'loaded' }) });

    resolveAdd?.();
    await inFlight;
    expect(panel.acceptedModel()).toBe('foo');

    pushLanes({ 'planner-foo': lane({ model: 'foo', runtime_state: 'loaded' }) });
    expect(panel.acceptedModel()).toBe('foo');
  });
});

/**
 * The outcome poll behind the pending note.
 *
 * addLane's 202 only says "accepted"; the planner refuses some loads in the
 * background (not enough VRAM for a second replica, the worker rejected the
 * command, the confirmation timed out) and until this poll existed that
 * refusal was a log line — the note stayed up forever. The poll asks the
 * orchestrator for the recorded outcome of the (provider, model) load:
 * "failed" turns the note into an error in the reopened picker, "succeeded"
 * stops the poll but keeps the note until the lane actually shows up, and
 * "running"/"unknown" leave everything exactly as it is.
 */
describe('LaneHealthPanel load outcome poll', () => {
  // Private tuning constants, reached the same way pickerProviderId is.
  const pollMs = (LaneHealthPanel as unknown as {
    LOAD_STATUS_POLL_INTERVAL_MS: number;
    LOAD_STATUS_POLL_CAP_MS: number;
  });
  let fixture: ComponentFixture<LaneHealthPanel>;
  let panel: LaneHealthPanel;
  let loadStatusCalls: number;
  /** What the next poll gets — set per test. */
  let loadStatusStub: () => Promise<{ status?: string; reason?: string }>;
  /** The poll's interval callback, held instead of waiting 2.5 s real time. */
  let pollTick: (() => void) | null = null;
  let clearedIntervals: number;
  let fakeNow: number;

  beforeEach(async () => {
    loadStatusCalls = 0;
    loadStatusStub = () => Promise.resolve({ status: 'running' });
    pollTick = null;
    clearedIntervals = 0;
    fakeNow = Date.now();
    // The suite runs zoneless, so fakeAsync's tick() is not available: hold
    // the poll's timer and fire it by hand, and advance Date.now for the cap.
    vi.spyOn(Date, 'now').mockImplementation(() => fakeNow);
    vi.spyOn(globalThis, 'setInterval').mockImplementation(
      ((callback: () => void) => {
        pollTick = callback;
        return 0;
      }) as unknown as typeof setInterval
    );
    vi.spyOn(globalThis, 'clearInterval').mockImplementation(() => {
      clearedIntervals += 1;
    });
    await TestBed.configureTestingModule({
      imports: [LaneHealthPanel],
      providers: [
        {
          provide: StatisticsService,
          useValue: {
            addLane: () => Promise.resolve(),
            getLaneLoadStatus: () => {
              loadStatusCalls += 1;
              return loadStatusStub();
            },
            getProviderModels: () => Promise.resolve([{ model_id: 1, model_name: 'foo' }]),
          },
        },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(LaneHealthPanel);
    panel = fixture.componentInstance;
    fixture.componentRef.setInput('lanesByProvider', {
      'gpu-01': { 'planner-foo': lane({ model: 'foo', runtime_state: 'running' }) },
    });
    fixture.componentRef.setInput('providerMeta', { 'gpu-01': { provider_id: 1 } });
    fixture.componentRef.setInput('selectedProvider', 'gpu-01');
    panel.loadModels.set([{ model_id: 1, model_name: 'foo' }] satisfies ProviderModel[]);
    (panel as unknown as { pickerProviderId: number | null }).pickerProviderId = 1;
    panel.selectedModel.set('foo');
    fixture.detectChanges();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /** Let the poll's promise chain (HTTP answer, then-handler) settle. */
  async function settle(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }

  /** One status-stream push, as the baseline describe does. */
  function pushLanes(next: Record<string, LaneSignalData>): void {
    const prev = panel.lanesByProvider;
    panel.lanesByProvider = { ...prev, 'gpu-01': next };
    panel.ngOnChanges({ lanesByProvider: new SimpleChange(prev, panel.lanesByProvider, false) });
  }

  /** The 202 arrives: the note is up and the poll runs behind it. */
  async function acceptLoad(): Promise<void> {
    await panel.handleAddLane();
    expect(panel.acceptedModel()).toBe('foo');
    expect(panel.pickerOpen()).toBe(false);
    expect(pollTick).not.toBeNull();
  }

  it('turns a background refusal into an error and re-offers the model', async () => {
    await acceptLoad();
    loadStatusStub = () =>
      Promise.resolve({
        status: 'failed',
        reason:
          'not enough free VRAM for this model: it needs ~48.4 GB in total, but the worker reports only 63.4 GB free',
      });

    pollTick?.(); // first poll fires
    await settle();

    // The note is gone, the picker came back with the recorded reason — where
    // a synchronous refusal lands — and the model may be retried.
    expect(panel.acceptedModel()).toBeNull();
    expect(panel.pickerOpen()).toBe(true);
    expect(panel.addError()).toBe(
      'Loading foo failed: not enough free VRAM for this model: it needs ~48.4 GB in total, but the worker reports only 63.4 GB free'
    );
    expect(filterLoadableModels(panel.loadModels(), panel.acceptedModel())).toEqual([
      { model_id: 1, model_name: 'foo' },
    ]);
    // And the poll is over with it — a stray later firing must not re-ask.
    expect(clearedIntervals).toBeGreaterThan(0);
    const calls = loadStatusCalls;
    pollTick?.();
    await settle();
    expect(loadStatusCalls).toBe(calls);
  });

  it('shows a reason-less refusal with a fallback instead of an empty message', async () => {
    await acceptLoad();
    loadStatusStub = () => Promise.resolve({ status: 'failed' });
    pollTick?.();
    await settle();
    expect(panel.addError()).toBe('Loading foo failed: no reason was recorded');
    expect(panel.acceptedModel()).toBeNull();
  });

  it('keeps the note after a recorded success until the lane shows up', async () => {
    // Clearing the note on "succeeded" would re-offer the model in the gap
    // between the planner's record and the next status push — the lane row
    // owns the note from here, not the outcome poll.
    await acceptLoad();
    loadStatusStub = () => Promise.resolve({ status: 'succeeded' });
    pollTick?.();
    await settle();
    expect(panel.acceptedModel()).toBe('foo');
    expect(panel.addError()).toBeNull();
    expect(clearedIntervals).toBeGreaterThan(0); // a terminal answer stops the poll

    // The lane arrives in the stream: the note goes.
    pushLanes({
      'planner-foo': lane({ model: 'foo', runtime_state: 'running' }),
      'planner-foo-2': lane({ model: 'foo', runtime_state: 'loaded' }),
    });
    expect(panel.acceptedModel()).toBeNull();
  });

  it('keeps waiting while the load is running or its outcome unrecorded', async () => {
    // "unknown" is what the orchestrator answers after a restart — it must
    // not read as a failure, the note just keeps saying what it says.
    await acceptLoad();
    pollTick?.();
    await settle();
    expect(panel.acceptedModel()).toBe('foo');
    expect(panel.addError()).toBeNull();
    expect(loadStatusCalls).toBe(1);

    loadStatusStub = () => Promise.resolve({ status: 'unknown' });
    pollTick?.();
    await settle();
    expect(panel.acceptedModel()).toBe('foo');
    expect(panel.addError()).toBeNull();
    expect(loadStatusCalls).toBe(2);
  });

  it('stops the poll when the operator switches provider', async () => {
    await acceptLoad();
    // The provider dropdown lives outside the panel: deliver the input change
    // the way pushLanes does, as the framework would. The second provider has
    // a provider_id like every real one — the switch guard compares the
    // picker's provider against the current one.
    panel.providerMeta = { 'gpu-01': { provider_id: 1 }, 'gpu-02': { provider_id: 2 } };
    panel.selectedProvider = 'gpu-02';
    panel.ngOnChanges({
      selectedProvider: new SimpleChange('gpu-01', 'gpu-02', true),
    });
    expect(panel.acceptedModel()).toBeNull();
    expect(clearedIntervals).toBeGreaterThan(0);
    pollTick?.();
    await settle();
    expect(loadStatusCalls).toBe(0);
  });

  it('stops the poll on a backend that predates the load_status route', async () => {
    // A 404/501 is not a blip to retry: the deployed Spring has no route, so
    // the poll would 404 until the cap. Stop and fall back to the
    // lane-appearance check, which needs no backend support.
    await acceptLoad();
    loadStatusStub = () =>
      Promise.reject(Object.assign(new Error('Not Found'), { status: 404 }));
    pollTick?.();
    await settle();
    expect(panel.acceptedModel()).toBe('foo'); // note untouched
    expect(clearedIntervals).toBeGreaterThan(0);
    pollTick?.();
    await settle();
    expect(loadStatusCalls).toBe(1);
  });

  it('gives up at the cap and leaves the note to the stream check', async () => {
    // Past the orchestrator's load command timeout the live outcome is gone;
    // re-asking for the same "running" is noise. The note stays — a lane that
    // still arrives resolves it via the stream.
    await acceptLoad();
    pollTick?.();
    await settle();
    expect(loadStatusCalls).toBe(1);

    fakeNow += pollMs.LOAD_STATUS_POLL_CAP_MS + 1;
    pollTick?.();
    await settle();
    expect(panel.acceptedModel()).toBe('foo');
    expect(clearedIntervals).toBeGreaterThan(0);
    const calls = loadStatusCalls;
    pollTick?.();
    await settle();
    expect(loadStatusCalls).toBe(calls);
  });

  it('drops a delayed answer from a superseded session of the same model', async () => {
    // The operator's retry starts a new polling session while the first
    // session's request is still in flight: that delayed answer describes
    // the old attempt and must not fail the new attempt's note. The
    // provider/model guards cannot tell the two sessions apart — same
    // provider, same model — only the session generation can.
    await acceptLoad();
    let firstCall = true;
    let releaseFirst: (value: { status: string; reason?: string }) => void = () => {};
    const delayed = new Promise<{ status: string; reason?: string }>((resolve) => {
      releaseFirst = resolve;
    });
    loadStatusStub = () => {
      if (firstCall) {
        firstCall = false;
        return delayed;
      }
      return Promise.resolve({ status: 'running' });
    };

    pollTick?.(); // session 1 asks; the answer is still on the wire
    await settle();
    expect(loadStatusCalls).toBe(1);

    // The operator retries the same model — the 202 starts a new polling
    // session. Reached directly, the way pickerProviderId is: what is under
    // test is what a new session does to an in-flight answer, not the picker
    // round-trip that leads here.
    (panel as unknown as { startLoadStatusPoll(pid: number, model: string): void }).startLoadStatusPoll(
      1,
      'foo'
    );

    // Session 1's answer lands now — it belongs to the attempt the note
    // replaced, not the one being polled.
    releaseFirst({ status: 'failed', reason: 'old attempt denied' });
    await settle();

    expect(panel.addError()).toBeNull();
    expect(panel.acceptedModel()).toBe('foo');
    expect(panel.pickerOpen()).toBe(false);
    // And the new session is untouched by it: it still polls and applies
    // its own answers.
    pollTick?.();
    await settle();
    expect(loadStatusCalls).toBe(2);
    expect(panel.addError()).toBeNull();
    expect(panel.acceptedModel()).toBe('foo');
  });
});

/**
 * Action feedback follows the worker it was reported on.
 *
 * An unload refusal or a calibration note is the answer to an action on one
 * specific worker: after the operator moves the dropdown, it means nothing
 * under the new worker's panel — neither the message that was already up nor
 * the answer of a call that is still in flight.
 */
describe('LaneHealthPanel action feedback follows the worker', () => {
  let fixture: ComponentFixture<LaneHealthPanel>;
  let panel: LaneHealthPanel;
  let unloadResult: { body?: unknown; error?: unknown };
  let settleUnload: (() => void) | null;

  beforeEach(async () => {
    unloadResult = {};
    settleUnload = null;
    await TestBed.configureTestingModule({
      imports: [LaneHealthPanel],
      providers: [
        {
          provide: StatisticsService,
          useValue: {
            unloadLane: () =>
              new Promise((resolve, reject) => {
                settleUnload = () =>
                  unloadResult.error ? reject(unloadResult.error) : resolve(unloadResult.body ?? {});
              }),
            getLaneLoadStatus: () => Promise.resolve({ status: 'running' }),
          },
        },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(LaneHealthPanel);
    panel = fixture.componentInstance;
    fixture.componentRef.setInput('lanesByProvider', {
      'gpu-01': { 'planner-foo': lane({ model: 'foo', runtime_state: 'running' }) },
      'gpu-02': { 'planner-bar': lane({ model: 'bar', runtime_state: 'running' }) },
    });
    fixture.componentRef.setInput('providerMeta', {
      'gpu-01': { provider_id: 1 },
      'gpu-02': { provider_id: 2 },
    });
    fixture.componentRef.setInput('selectedProvider', 'gpu-01');
    fixture.detectChanges();
  });

  /** Move the provider dropdown, as the framework would. */
  function switchTo(provider: string): void {
    panel.selectedProvider = provider;
    panel.ngOnChanges({ selectedProvider: new SimpleChange('gpu-01', provider, true) });
  }

  it('drops an unload error when the operator switches worker', async () => {
    unloadResult.error = { status: 500, error: 'denied by worker-a' };
    const pending = panel.handleUnload('planner-foo');
    settleUnload?.();
    await pending;
    expect(panel.unloadError()).toBe('Unload of planner-foo failed: denied by worker-a');

    switchTo('gpu-02');
    expect(panel.unloadError()).toBeNull();
  });

  it('drops a sleep/wake error on the switch as well', async () => {
    panel.sleepWakeError.set('Sleep of planner-foo failed: the worker said no');

    switchTo('gpu-02');
    expect(panel.sleepWakeError()).toBeNull();
  });

  it('clears the spinner of a call that is still in flight at the switch', async () => {
    panel.handleUnload('planner-foo');
    expect(panel.unloadingLaneId()).toBe('planner-foo');

    switchTo('gpu-02');
    expect(panel.unloadingLaneId()).toBeNull();
  });

  it('does not show a stale unload error under the switched-to worker', async () => {
    const pending = panel.handleUnload('planner-foo');
    // The call is still in flight when the operator switches.
    switchTo('gpu-02');

    unloadResult.error = { status: 500, error: 'denied by worker-a' };
    settleUnload?.();
    await pending;

    // The refusal belongs to gpu-01; gpu-02's panel shows nothing.
    expect(panel.unloadError()).toBeNull();
  });
});
