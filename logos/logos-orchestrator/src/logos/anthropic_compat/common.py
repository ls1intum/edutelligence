# src/logos/anthropic_compat/common.py
"""Pieces shared by both Anthropic Messages translations.

Claude Code reaches Logos through the Anthropic Messages API
(``POST /v1/messages``). vLLM serves that surface itself, so a request that
ends on a workernode is forwarded verbatim and nothing in this package runs.
Cloud upstreams are the exception: Azure OpenAI and every other OpenAI-shaped
resource expose ``chat/completions`` and ``responses`` and have no Messages
route at all, so forwarding the path like-for-like returns 404 before the
model sees anything.

This module holds what both target dialects need: which upstream speaks which
dialect, how an Anthropic content block maps onto an OpenAI one, and the SSE
plumbing — a parser for the upstream event stream and a writer that emits a
protocol-correct Anthropic one.
"""

from __future__ import annotations

import codecs
import json
import re
import secrets
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# The single inbound path this package translates. ``/v1/messages`` is what the
# Anthropic SDKs (and therefore Claude Code) post to; Logos also serves the
# ``/openai`` prefix, which the route layer has already rewritten to ``v1/...``
# by the time a path reaches here.
MESSAGES_PATH = "v1/messages"

# OpenAI's reasoning families — the o-series and gpt-5 — under both their bare
# names and any vendor prefix ("openai/gpt-5.1"). They take a different
# parameter set on chat/completions than every older model.
_REASONING_MODEL_RE = re.compile(r"^(?:o\d|gpt-5)", re.IGNORECASE)


class UpstreamDialect(str, Enum):
    """Which API surface the resolved upstream actually serves.

    ``NATIVE`` means the upstream serves the Anthropic Messages API itself —
    a vLLM lane, an Anthropic cloud resource, or another Logos instance — and
    the request is forwarded untouched, which is the behaviour that existed
    before this package.
    """

    NATIVE = "native"
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


def is_messages_path(request_path: Optional[str]) -> bool:
    """Whether an inbound request path addresses the Anthropic Messages API."""
    if not request_path:
        return False
    path = request_path.split("?", 1)[0].strip("/")
    return path == MESSAGES_PATH


def is_reasoning_model(model_name: Optional[str]) -> bool:
    """Whether this model is one of the OpenAI reasoning families.

    The two families take mutually exclusive parameter sets on
    chat/completions, and getting it wrong is a 400 before the model sees
    anything: a reasoning model rejects ``max_tokens``, ``temperature`` and
    ``top_p``, while everything older rejects ``reasoning_effort``. Only the
    name is available to decide — the served name, with any vendor prefix
    stripped.
    """
    name = (model_name or "").rsplit("/", 1)[-1]
    return bool(_REASONING_MODEL_RE.match(name))


def wants_max_completion_tokens(model_name: Optional[str]) -> bool:
    """Whether this model needs ``max_completion_tokens`` on chat/completions.

    Anthropic requires ``max_tokens`` on every request, so the translation
    always has a value to forward; only its name differs by model family.
    """
    return is_reasoning_model(model_name)


def new_message_id(upstream_id: Any) -> str:
    """An Anthropic-shaped message id, derived from the upstream one.

    Anthropic ids start with ``msg_``; clients key their own bookkeeping on
    that prefix. The upstream id is kept as the suffix so a Logos log line and
    the client's id still point at the same upstream request.
    """
    raw = str(upstream_id or "").strip()
    if raw.startswith("msg_"):
        return raw
    suffix = raw or secrets.token_hex(12)
    return f"msg_{suffix}"


# ── content blocks ──────────────────────────────────────────────────────────


def normalize_content(content: Any) -> List[Dict[str, Any]]:
    """Return an Anthropic message ``content`` as a list of blocks.

    The Messages API accepts a bare string as shorthand for a single text
    block; every other shape is already a list of blocks.
    """
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return [{"type": "text", "text": str(content)}]


def system_to_text(system: Any) -> str:
    """Flatten an Anthropic ``system`` field into one string.

    ``system`` is either a string or a list of text blocks (Claude Code sends
    the list form, one block per prompt section). Both OpenAI dialects take a
    single string, so the blocks are joined the way the model would have seen
    them concatenated.
    """
    if not system:
        return ""
    if isinstance(system, str):
        return system
    parts = [str(block.get("text") or "") for block in normalize_content(system) if block.get("type") == "text"]
    return "\n\n".join(part for part in parts if part)


# Roles a client may put on a turn to mean "this is an instruction, not
# something the user or the model said".
_SYSTEM_ROLES = frozenset({"system", "developer"})


def system_and_messages(payload: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """The system prompt and the conversation, with inline system turns hoisted.

    The Messages API defines two roles for ``messages`` — user and assistant —
    and carries the system prompt in its own top-level field. Claude Code
    nonetheless injects ``role: "system"`` turns mid-conversation, and
    translating one literally puts a system message in the middle of a
    chat/completions body. OpenAI tolerates that; a chat template does not, and
    an upstream serving one answers "System message must be at the beginning."
    with a 400 before the model sees the request.

    Their text joins the system prompt in the order it appeared. That keeps the
    instructions — dropping them would silently change what the model was told
    — and leaves the remaining turns strictly alternating, which is what the
    templates that reject a stray system message also tend to require. Turning
    them into user turns would instead produce two user turns in a row.
    """
    system_parts = [system_to_text(payload.get("system"))]
    conversation: List[Dict[str, Any]] = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() in _SYSTEM_ROLES:
            # Content here has the same string-or-text-blocks shape as the
            # top-level system field, so it flattens the same way.
            system_parts.append(system_to_text(message.get("content")))
            continue
        conversation.append(message)
    return "\n\n".join(part for part in system_parts if part), conversation


def image_data_url(block: Dict[str, Any]) -> Optional[str]:
    """Turn an Anthropic image block into a ``data:``/``https:`` URL.

    Anthropic carries images as ``{"source": {"type": "base64", "media_type":
    ..., "data": ...}}`` or ``{"source": {"type": "url", "url": ...}}``; both
    OpenAI dialects take a URL, and a base64 payload becomes a data URI.
    """
    source = block.get("source")
    if not isinstance(source, dict):
        return None
    if source.get("type") == "url" and source.get("url"):
        return str(source["url"])
    data = source.get("data")
    if not data:
        return None
    media_type = str(source.get("media_type") or "image/png")
    return f"data:{media_type};base64,{data}"


def tool_result_text(block: Dict[str, Any]) -> str:
    """Flatten a ``tool_result`` block's content into plain text.

    The block's ``content`` is a string, a list of text blocks, or a list of
    mixed blocks (a tool that returned an image). Neither OpenAI dialect can
    carry a non-text tool result, so non-text blocks are summarised rather
    than dropped silently — the model still learns that something came back.
    """
    content = block.get("content")
    if isinstance(content, str):
        return content
    parts: List[str] = []
    for inner in normalize_content(content):
        kind = inner.get("type")
        if kind == "text":
            parts.append(str(inner.get("text") or ""))
        elif kind == "image":
            parts.append("[image omitted: this upstream cannot receive images in tool results]")
        else:
            parts.append(json.dumps(inner, ensure_ascii=False))
    return "\n".join(part for part in parts if part)


def json_arguments(value: Any) -> str:
    """Serialize a tool call's input the way OpenAI expects it: a JSON string."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def parse_arguments(raw: Any) -> Dict[str, Any]:
    """Parse an OpenAI tool-call argument string into an Anthropic ``input``.

    A model can emit arguments that are not valid JSON (truncated by a length
    stop, or simply malformed). Anthropic's ``tool_use.input`` must be an
    object, so an unparsable value is handed over under a ``_raw`` key instead
    of failing the whole response.
    """
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {"_raw": text}
    return parsed if isinstance(parsed, dict) else {"_raw": parsed}


def disables_parallel_tool_use(tool_choice: Any) -> bool:
    """Whether the client asked for at most one tool call per turn.

    Anthropic expresses that as a flag on ``tool_choice``; both OpenAI
    surfaces spell it ``parallel_tool_calls`` and default it to true. Dropping
    it lets a turn the client deliberately limited produce several calls — and
    for an agent that is several side effects instead of one.
    """
    return isinstance(tool_choice, dict) and bool(tool_choice.get("disable_parallel_tool_use"))


def anthropic_tools(tools: Any) -> List[Dict[str, Any]]:
    """Anthropic tool definitions -> OpenAI ``function`` definitions.

    Anthropic's server-side tools (web search, code execution — anything whose
    entry carries a ``type`` instead of an ``input_schema``) have no OpenAI
    equivalent and are skipped: forwarding them would be rejected as an
    unknown function shape.
    """
    result: List[Dict[str, Any]] = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        schema = tool.get("input_schema")
        if not isinstance(schema, dict):
            continue
        result.append(
            {
                "name": str(tool["name"]),
                "description": str(tool.get("description") or ""),
                "parameters": schema,
            }
        )
    return result


# ── stop reasons ────────────────────────────────────────────────────────────

# OpenAI finish_reason -> Anthropic stop_reason. "content_filter" has no
# Anthropic counterpart; "end_turn" is the honest answer for the client, and
# the filtered content is already absent from the body either way.
_STOP_REASONS = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "end_turn",
}


def stop_reason(finish_reason: Any, *, saw_tool_call: bool = False) -> Optional[str]:
    """Map an OpenAI finish reason onto an Anthropic stop reason.

    ``saw_tool_call`` covers upstreams that report ``stop`` even though the
    turn ended in a tool call: a client that reads ``end_turn`` there stops
    the agent loop instead of running the tool.
    """
    if finish_reason is None:
        return "tool_use" if saw_tool_call else None
    mapped = _STOP_REASONS.get(str(finish_reason), "end_turn")
    return "tool_use" if saw_tool_call and mapped == "end_turn" else mapped


# Usage keys Logos adds to a cloud response after the fact — the priced cost of
# the request. Not part of either API, but the native Messages path surfaces
# them, so the translated path has to as well or a cloud model's cost silently
# disappears for clients that reach it through /v1/messages.
LOGOS_USAGE_EXTRAS = ("cost", "cost_currency")


def usage_extras(usage: Any) -> Dict[str, Any]:
    """The Logos-added usage fields present on an upstream usage object."""
    if not isinstance(usage, dict):
        return {}
    return {key: usage[key] for key in LOGOS_USAGE_EXTRAS if key in usage}


def usage_block(input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> Dict[str, int]:
    """The ``usage`` object of an Anthropic message.

    Cached prompt tokens are reported by both dialects as a subset of the
    input tokens, which is also how Anthropic's ``cache_read_input_tokens``
    is defined, so the value carries over unchanged. Logos never writes to an
    upstream prompt cache on the client's behalf, so nothing is ever charged
    as ``cache_creation_input_tokens``.
    """
    return {
        "input_tokens": max(int(input_tokens or 0), 0),
        "output_tokens": max(int(output_tokens or 0), 0),
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": max(int(cached_tokens or 0), 0),
    }


def error_body(message: str, error_type: str = "api_error") -> Dict[str, Any]:
    """An Anthropic-shaped error body."""
    return {"type": "error", "error": {"type": error_type, "message": str(message)}}


# ── SSE ─────────────────────────────────────────────────────────────────────


def sse(event: str, data: Dict[str, Any]) -> bytes:
    """Encode one Anthropic SSE event.

    Anthropic names every event twice — once in the ``event:`` line and once
    in the payload's ``type`` — and clients read both.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


class SSEDecoder:
    """Incremental decoder for an upstream SSE byte stream.

    Chunks arrive on arbitrary byte boundaries, so events are only released
    once their terminating blank line has been seen. Yields
    ``(event_name, data)`` pairs; ``event_name`` is ``None`` for streams that
    omit the ``event:`` line, which is how chat/completions frames its events
    (the Responses API names every one of them).

    A byte boundary can also fall inside a multi-byte character — one "ü" or
    one emoji split across two chunks — so decoding is incremental too.
    Decoding each chunk on its own would turn those into replacement
    characters before the translation ever sees them.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def feed(self, chunk: Any) -> List[Tuple[Optional[str], str]]:
        if isinstance(chunk, bytes):
            chunk = self._decoder.decode(chunk)
        self._buffer += str(chunk or "")
        events: List[Tuple[Optional[str], str]] = []
        while True:
            # Upstreams terminate events with \n\n; a proxy in between may
            # have normalised that to \r\n\r\n.
            index = self._buffer.find("\n\n")
            crlf_index = self._buffer.find("\r\n\r\n")
            if crlf_index != -1 and (index == -1 or crlf_index < index):
                raw, self._buffer = self._buffer[:crlf_index], self._buffer[crlf_index + 4 :]
            elif index != -1:
                raw, self._buffer = self._buffer[:index], self._buffer[index + 2 :]
            else:
                break
            parsed = _parse_sse_block(raw)
            if parsed is not None:
                events.append(parsed)
        return events


def _parse_sse_block(raw: str) -> Optional[Tuple[Optional[str], str]]:
    """Parse one SSE block into ``(event_name, data)``; ``None`` if empty."""
    event_name: Optional[str] = None
    data_lines: List[str] = []
    for line in raw.splitlines():
        line = line.rstrip("\r")
        if line.startswith(":") or not line.strip():
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event_name = value.strip()
        elif field == "data":
            data_lines.append(value)
    if not data_lines and event_name is None:
        return None
    return event_name, "\n".join(data_lines)


class AnthropicStreamWriter:
    """Builds a protocol-correct Anthropic event stream from upstream deltas.

    The Messages stream is a state machine, not a sequence of independent
    frames: exactly one content block is open at a time, block indices count
    up from zero without gaps, and the terminal ``message_delta`` carries the
    stop reason and the output-token count. Both dialect translators drive
    this writer instead of assembling those events themselves.
    """

    def __init__(self, message_id: str, model: str) -> None:
        self._id = message_id
        self._model = model
        self._started = False
        self._finished = False
        self._next_index = 0
        self._open_key: Optional[str] = None
        self._input_tokens = 0
        self._output_tokens = 0
        self._cached_tokens = 0
        self._usage_extras: Dict[str, Any] = {}

    @property
    def started(self) -> bool:
        return self._started

    def record_usage(
        self,
        *,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cached_tokens: Optional[int] = None,
        extras: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Remember token counts for the message_start / message_delta events."""
        if input_tokens:
            self._input_tokens = int(input_tokens)
        if output_tokens:
            self._output_tokens = int(output_tokens)
        if cached_tokens:
            self._cached_tokens = int(cached_tokens)
        if extras:
            self._usage_extras.update(extras)

    def start(self) -> List[bytes]:
        """Emit ``message_start`` once; later calls are no-ops.

        Also the single gate on the finished state: every content method goes
        through here, so once the stream has been closed — by ``stop`` or by
        ``error`` — nothing more can reach the client. A translator that still
        holds buffered content when the turn fails would otherwise emit it
        after the terminal event.
        """
        if self._started or self._finished:
            return []
        self._started = True
        return [
            sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": self._id,
                        "type": "message",
                        "role": "assistant",
                        "model": self._model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": usage_block(self._input_tokens, 0, self._cached_tokens),
                    },
                },
            )
        ]

    def text(self, text: str) -> List[bytes]:
        """Append text, opening a text block if one is not already open."""
        if not text or self._finished:
            return []
        out = self.start()
        out += self._open("text:0", {"type": "text", "text": ""})
        out.append(
            sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self._next_index - 1,
                    "delta": {"type": "text_delta", "text": text},
                },
            )
        )
        return out

    def tool_use(self, key: str, tool_id: str, name: str) -> List[bytes]:
        """Open a ``tool_use`` block for one upstream tool call."""
        if self._finished:
            return []
        out = self.start()
        out += self._open(
            f"tool:{key}",
            {"type": "tool_use", "id": tool_id, "name": name, "input": {}},
        )
        return out

    def tool_arguments(self, key: str, partial_json: str) -> List[bytes]:
        """Append argument text to an already-open ``tool_use`` block."""
        if not partial_json or self._finished or self._open_key != f"tool:{key}":
            return []
        return [
            sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self._next_index - 1,
                    "delta": {"type": "input_json_delta", "partial_json": partial_json},
                },
            )
        ]

    def stop(self, reason: Optional[str]) -> List[bytes]:
        """Close the stream with ``message_delta`` + ``message_stop``.

        Safe to call twice — the terminal events are emitted once, so a
        translator may close on the upstream's terminal event and again when
        the byte stream ends.
        """
        if self._finished:
            return []
        out = self.start()
        out += self._close()
        self._finished = True
        # The whole settled usage, not just the output count. Both upstream
        # dialects report usage in a terminal frame, which arrives long after
        # message_start has gone out with zeros — so this is the only event
        # that can carry the real prompt, cache and cost figures.
        final_usage: Dict[str, Any] = usage_block(self._input_tokens, self._output_tokens, self._cached_tokens)
        final_usage.update(self._usage_extras)
        out.append(
            sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": reason or "end_turn", "stop_sequence": None},
                    "usage": final_usage,
                },
            )
        )
        out.append(sse("message_stop", {"type": "message_stop"}))
        return out

    def error(self, message: str, error_type: str = "api_error") -> List[bytes]:
        """Emit an Anthropic ``error`` event mid-stream.

        Clients treat this as the terminal event, so nothing follows it — in
        particular not the ``message_stop`` a successful turn ends with, which
        would otherwise read as a complete answer.
        """
        if self._finished:
            return []
        out = self._close()
        self._finished = True
        out.append(sse("error", error_body(message, error_type)))
        return out

    def _open(self, key: str, block: Dict[str, Any]) -> List[bytes]:
        """Start content block ``key``, closing whichever one is open."""
        if self._open_key == key:
            return []
        out = self._close()
        self._open_key = key
        index = self._next_index
        self._next_index += 1
        out.append(
            sse(
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": block},
            )
        )
        return out

    def _close(self) -> List[bytes]:
        if self._open_key is None:
            return []
        self._open_key = None
        return [sse("content_block_stop", {"type": "content_block_stop", "index": self._next_index - 1})]
