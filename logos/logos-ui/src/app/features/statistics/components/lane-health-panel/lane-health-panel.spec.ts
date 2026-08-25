import { formatContextWindow, messageIn } from './lane-health-panel';

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
