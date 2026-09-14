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
    assert gate.has_output(b'data: {"choices": [{"delta": {"reasoning_content": "thinking"}}]}\n') is True


# --- SSE framing: comments, control fields, no-space data ------------------


def test_sse_comments_are_metadata():
    """: keepalive comments hold the connection open and carry no output —
    they must not open the gate."""
    assert _SsePreCommitGate._line_is_output(b": keepalive") is False
    assert _SsePreCommitGate._line_is_output(b":") is False


def test_id_and_retry_fields_are_metadata():
    """The last-event id and the reconnect delay steer the client's
    connection, not the answer."""
    assert _SsePreCommitGate._line_is_output(b"id: 1") is False
    assert _SsePreCommitGate._line_is_output(b"retry: 3000") is False


def test_no_space_data_line_is_parsed():
    """The single space after "data:" is optional — data:{...} is valid
    SSE, so a role-only frame without the space is still metadata, a
    content frame without it is still output, and data:[DONE] is the
    terminal either way."""
    assert _SsePreCommitGate._line_is_output(b'data:{"choices": [{"delta": {"role": "assistant"}}]}') is False
    assert _SsePreCommitGate._line_is_output(b'data:{"choices": [{"delta": {"content": "hi"}}]}') is True
    assert _SsePreCommitGate._line_is_output(b"data:[DONE]") is True


def test_unknown_field_is_output():
    """A field name the SSE spec does not define is no proof of a non-SSE
    body either way — the gate starts the stream, when in doubt."""
    assert _SsePreCommitGate._line_is_output(b"foo: bar") is True


def test_has_output_holds_across_keepalives_and_control_fields():
    """The full prefix a provider can send before the first delta —
    keepalive, id, retry, and a no-space role-only frame — must all stay
    behind the gate; the content delta that follows opens it."""
    gate = _SsePreCommitGate(text_stream=True)
    assert gate.has_output(b": keepalive\n\n") is False
    assert gate.has_output(b"id: 1\nretry: 3000\n\n") is False
    assert gate.has_output(b'data:{"choices": [{"delta": {"role": "assistant", "content": ""}}]}\n\n') is False
    assert gate.has_output(b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n') is True
