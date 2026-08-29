import {
  countLiveLanesByModel,
  filterLoadableModels,
  formatContextWindow,
  laneSleepAction,
  messageIn,
} from './lane-health-panel';
import { LaneSignalData } from '../../statistics.models';

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
 * Rounded thousands, because the row is a dense line of stats read to spot the
 * roomy lane — the exact token count is never what is being asked.
 */
describe('formatContextWindow', () => {
  it('abbreviates thousands', () => {
    expect(formatContextWindow(262144)).toBe('262k');
    expect(formatContextWindow(111200)).toBe('111k');
    expect(formatContextWindow(40960)).toBe('41k');
    expect(formatContextWindow(1000)).toBe('1k');
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
    vllm: true,
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
    // Ollama lanes report "unsupported"; a vLLM lane that never slept reports
    // "unknown" until its first transition.
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
