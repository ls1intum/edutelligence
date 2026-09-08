"""Regression tests for _SsePreCommitGate's reasoning handling.

A thinking model streams its reasoning (chat ``reasoning_content`` / native
``thinking_delta``) *before* any visible text. The gate must treat non-empty
reasoning as generated output — otherwise a whole reasoning phase is buffered
behind the pre-commit window, defeating streaming, and a worker failure right
after the reasoning (before any text) looks as though no output was produced
and can no longer be re-dispatched on resume.
"""

from logos.main import _SsePreCommitGate


def _line(frame: str) -> bytes:
    return f"data: {frame}\n".encode("utf-8").rstrip(b"\n")


# --- chat path (choices[].delta) -------------------------------------------


def test_chat_reasoning_content_counts_as_output():
    """A chat delta that only carries reasoning_content is output, not the
    metadata it used to be classified as."""
    frame = '{"choices": [{"delta": {"role": "assistant", "reasoning_content": "Let me work this out"}}]}'
    assert _SsePreCommitGate._line_is_output(_line(frame)) is True


def test_chat_empty_reasoning_content_is_metadata():
    """An empty reasoning_content with no content/structured keys is still
    protocol metadata — the gate must not start the stream on it."""
    frame = '{"choices": [{"delta": {"role": "assistant", "reasoning_content": ""}}]}'
    assert _SsePreCommitGate._line_is_output(_line(frame)) is False


def test_chat_content_still_counts_as_output():
    frame = '{"choices": [{"delta": {"role": "assistant", "content": "hi"}}]}'
    assert _SsePreCommitGate._line_is_output(_line(frame)) is True


def test_chat_role_only_delta_is_metadata():
    frame = '{"choices": [{"delta": {"role": "assistant"}}]}'
    assert _SsePreCommitGate._line_is_output(_line(frame)) is False


# --- native dialect (content_block_delta) ----------------------------------


def test_native_thinking_delta_counts_as_output():
    """A native thinking_delta carries its output in ``thinking``, not
    ``text`` — it must start the stream like a text_delta does."""
    frame = '{"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "working it out"}}'
    assert _SsePreCommitGate._line_is_output(_line(frame)) is True


def test_native_empty_thinking_delta_is_metadata():
    frame = '{"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": ""}}'
    assert _SsePreCommitGate._line_is_output(_line(frame)) is False


def test_native_text_delta_still_counts_as_output():
    frame = '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}'
    assert _SsePreCommitGate._line_is_output(_line(frame)) is True


def test_native_empty_text_delta_is_metadata():
    frame = '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": ""}}'
    assert _SsePreCommitGate._line_is_output(_line(frame)) is False


# --- end-to-end through has_output (line framing) --------------------------


def test_has_output_fires_on_first_reasoning_chunk():
    gate = _SsePreCommitGate(text_stream=True)
    # A role-only open is metadata; the reasoning delta that follows starts
    # the stream — no ordinary text is ever needed.
    assert gate.has_output(b'data: {"choices": [{"delta": {"role": "assistant"}}]}\n') is False
    assert (
        gate.has_output(b'data: {"choices": [{"delta": {"reasoning_content": "thinking"}}]}\n')
        is True
    )
