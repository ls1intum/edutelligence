# src/logos/anthropic_compat/messages_api.py
"""OpenAI Chat Completions ⇄ Anthropic Messages.

The mirror of :mod:`chat_completions`. That module serves the Messages API on
upstreams that only have ``chat/completions``; this one serves
``chat/completions`` on upstreams that only have the Messages API.

Claude on Azure Foundry is the upstream that needs it. Foundry exposes Claude
deployments on ``/anthropic/v1/messages`` and nowhere else — there is no
OpenAI-shaped route to forward a chat/completions request to, by Microsoft's
and Anthropic's design rather than by configuration. Without a translation the
body reaches the Messages API as-is, where the overlap between the two
dialects decides the outcome: a plain prompt happens to parse and comes back
in the wrong shape, while an OpenAI ``tools`` array, ``max_completion_tokens``
or an absent ``max_tokens`` is a 400.

Unsupported OpenAI fields are ignored rather than forwarded, which is what
Anthropic's own OpenAI compatibility layer does and what an OpenAI client
expects; forwarding them would turn a request the client considers valid into
an upstream error.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from logos.anthropic_compat.common import (
    SSEDecoder,
    finish_reason,
    json_arguments,
    new_completion_id,
    normalize_content,
    openai_usage_block,
    parse_arguments,
    tool_result_text,
)
from logos.context_budget import DEFAULT_OUTPUT_RESERVE_TOKENS

# Roles that carry instructions rather than conversation. Both are hoisted
# into Anthropic's top-level ``system`` field.
_SYSTEM_ROLES = frozenset({"system", "developer"})

# Roles that carry the answer of a tool the model called.
_TOOL_ROLES = frozenset({"tool", "function"})

# Anthropic caps ``temperature`` at 1.0 where OpenAI allows 2.0. A value above
# the cap is a 400, so it is clamped rather than dropped — the client asked for
# "as random as this API goes", and that is what it gets.
_MAX_TEMPERATURE = 1.0


def to_messages(payload: Dict[str, Any], *, model_name: Optional[str] = None) -> Dict[str, Any]:
    """Translate a chat/completions request into an Anthropic Messages one."""
    if not isinstance(payload, dict):
        return payload

    system_parts: List[str] = []
    turns: List[Dict[str, Any]] = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").lower()
        if role in _SYSTEM_ROLES:
            # OpenAI allows a system turn anywhere in the conversation and
            # Anthropic has exactly one system field, so they are concatenated
            # in the order they appeared — the same resolution Anthropic's own
            # compatibility layer documents.
            text = _flatten_text(message.get("content"))
            if text:
                system_parts.append(text)
            continue
        for turn in _translate_message(role, message):
            _append_turn(turns, turn)

    result: Dict[str, Any] = {
        "model": payload.get("model") or model_name,
        "messages": turns,
        # Required by the Messages API and optional in OpenAI's, so a request
        # that names no cap needs one supplied. The scheduler already reserves
        # this many tokens of context for an uncapped request, so anything
        # smaller here would cut answers short inside a window Logos had
        # already set aside for them.
        "max_tokens": _max_tokens(payload),
    }

    system = "\n".join(system_parts)
    if system:
        result["system"] = system

    temperature = _number(payload.get("temperature"))
    if temperature is not None:
        result["temperature"] = min(max(temperature, 0.0), _MAX_TEMPERATURE)
    top_p = _number(payload.get("top_p"))
    if top_p is not None:
        result["top_p"] = top_p

    stop = payload.get("stop")
    if isinstance(stop, str) and stop:
        result["stop_sequences"] = [stop]
    elif isinstance(stop, list):
        sequences = [str(item) for item in stop if isinstance(item, str) and item]
        if sequences:
            result["stop_sequences"] = sequences

    if payload.get("stream") is not None:
        # ``stream_options`` is deliberately not carried over: the Messages API
        # rejects it, and it has no purpose there because usage arrives in
        # message_start and message_delta on every stream. ``Executor.
        # _streaming_payload`` already leaves it off a Messages URL.
        result["stream"] = payload["stream"]

    tools = _tools(payload.get("tools"))
    if tools:
        result["tools"] = tools
        choice = _tool_choice(payload.get("tool_choice"), payload.get("parallel_tool_calls"))
        if choice is not None:
            result["tool_choice"] = choice

    return result


def _max_tokens(payload: Dict[str, Any]) -> int:
    """The output cap for a Messages request, which must always carry one.

    Both OpenAI spellings are accepted — ``max_completion_tokens`` is the one
    the reasoning families take, and a client that has been migrated to it
    would otherwise look like a client that named no cap at all.
    """
    for key in ("max_completion_tokens", "max_tokens"):
        raw = payload.get(key)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return DEFAULT_OUTPUT_RESERVE_TOKENS


def _number(value: Any) -> Optional[float]:
    """``value`` as a float, or ``None`` if it is not a number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flatten_text(content: Any) -> str:
    """The plain text of an OpenAI ``content`` field.

    It is either a string or the multimodal list form; non-text parts have no
    place in a system prompt and are skipped.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [
        str(part.get("text") or "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
    ]
    return "\n".join(parts)


def _translate_message(role: str, message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One chat/completions message -> the Anthropic turns it becomes."""
    if role in _TOOL_ROLES:
        # A tool answer is a user turn in the Messages API. Consecutive ones
        # are merged by _append_turn, which is what Anthropic requires: every
        # tool_result for the preceding assistant turn has to arrive in a
        # single user turn.
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": str(message.get("tool_call_id") or message.get("name") or ""),
                        "content": _flatten_text(message.get("content")),
                    }
                ],
            }
        ]

    if role == "assistant":
        return _assistant_turn(message)

    blocks = _content_blocks(message.get("content"))
    return [{"role": "user", "content": blocks}] if blocks else []


def _assistant_turn(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """An assistant message -> one Anthropic turn of text and tool_use blocks."""
    blocks = _content_blocks(message.get("content"))

    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        # The deprecated single-call spelling. Clients that still send it would
        # otherwise lose the call, and the conversation stops making sense at
        # the tool result that answers it.
        legacy = message.get("function_call")
        calls = [{"function": legacy}] if isinstance(legacy, dict) else []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = str(function.get("name") or "")
        if not name:
            continue
        blocks.append(
            {
                "type": "tool_use",
                # Anthropic pairs a tool_result to its call by id and rejects an
                # empty one. The legacy spelling carries none, so the position
                # stands in — the matching tool message has no id either.
                "id": str(call.get("id") or f"call_{index}"),
                "name": name,
                "input": parse_arguments(function.get("arguments")),
            }
        )

    # An assistant turn with neither text nor a call — a client echoing back
    # {"role": "assistant", "content": ""} — has no Anthropic representation:
    # empty content is a 400 there. Dropping it loses nothing the model said.
    return [{"role": "assistant", "content": blocks}] if blocks else []


def _content_blocks(content: Any) -> List[Dict[str, Any]]:
    """An OpenAI ``content`` field -> Anthropic content blocks.

    Audio and file parts are skipped: the Messages API has no counterpart, and
    forwarding an unknown block type fails the whole request rather than the
    one part that cannot be carried.
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return []

    blocks: List[Dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text" and part.get("text"):
            blocks.append({"type": "text", "text": str(part["text"])})
        elif kind == "image_url":
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            block = _image_block(str(url or ""))
            if block:
                blocks.append(block)
    return blocks


def _image_block(url: str) -> Optional[Dict[str, Any]]:
    """An OpenAI image URL -> an Anthropic image block.

    The inverse of ``common.image_data_url``: a ``data:`` URI is unpacked into
    the base64 source Anthropic expects, and a remote URL is passed on as one.
    """
    if not url:
        return None
    if not url.startswith("data:"):
        return {"type": "image", "source": {"type": "url", "url": url}}
    header, _, data = url.partition(",")
    if not data or ";base64" not in header:
        # A data: URI that is not base64 (percent-encoded text) has no
        # Anthropic image source to map onto.
        return None
    media_type = header[len("data:") :].split(";", 1)[0] or "image/png"
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _append_turn(turns: List[Dict[str, Any]], turn: Dict[str, Any]) -> None:
    """Add a turn, merging it into the previous one if the roles match.

    Two user turns in a row happen routinely after a translation — several
    ``role: tool`` messages answering parallel calls, or a tool answer
    followed by the user's next prompt — and the Messages API wants each side
    of the conversation as one turn.
    """
    if turns and turns[-1]["role"] == turn["role"]:
        turns[-1]["content"].extend(turn["content"])
        return
    turns.append(turn)


def _tools(tools: Any) -> List[Dict[str, Any]]:
    """OpenAI function definitions -> Anthropic tool definitions.

    ``strict`` is dropped: Anthropic has no per-tool schema enforcement, and
    the field is ignored by Anthropic's own compatibility layer too. Tool types
    other than ``function`` (OpenAI's built-ins) have no counterpart and are
    skipped rather than forwarded as an unknown shape.
    """
    result: List[Dict[str, Any]] = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else None
        if function is None or (tool.get("type") or "function") != "function":
            continue
        name = str(function.get("name") or "")
        if not name:
            continue
        schema = function.get("parameters")
        result.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                # Required by the Messages API; a function declared without
                # parameters becomes one that takes an empty object.
                "input_schema": schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
            }
        )
    return result


def _tool_choice(choice: Any, parallel_tool_calls: Any) -> Optional[Dict[str, Any]]:
    """OpenAI ``tool_choice`` -> the Anthropic spelling.

    ``parallel_tool_calls: false`` folds in here because Anthropic carries it
    as a flag on ``tool_choice`` rather than as a field of its own. It is the
    one OpenAI field whose omission changes behaviour rather than losing
    detail: a turn the client deliberately limited to one call would otherwise
    be free to make several, and for an agent that is several side effects.
    """
    result: Optional[Dict[str, Any]] = None
    if isinstance(choice, str):
        result = {"auto": {"type": "auto"}, "none": {"type": "none"}, "required": {"type": "any"}}.get(choice)
    elif isinstance(choice, dict):
        function = choice.get("function") if isinstance(choice.get("function"), dict) else {}
        if function.get("name"):
            result = {"type": "tool", "name": str(function["name"])}

    if parallel_tool_calls is False:
        result = dict(result or {"type": "auto"})
        result["disable_parallel_tool_use"] = True
    return result


# ── response ────────────────────────────────────────────────────────────────


def from_message(body: Dict[str, Any], *, model_name: Optional[str] = None) -> Dict[str, Any]:
    """Translate an Anthropic message into a chat/completions response body."""
    content: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for block in normalize_content(body.get("content")):
        kind = block.get("type")
        if kind == "text" and block.get("text"):
            content.append(str(block["text"]))
        elif kind == "tool_use":
            tool_calls.append(
                {
                    "id": str(block.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": json_arguments(block.get("input")),
                    },
                }
            )
        elif kind == "tool_result":
            # Only a server-side tool produces one in an assistant message, and
            # chat/completions has nowhere to put a result the model already
            # consumed. Its text is kept so the answer is not silently short.
            text = tool_result_text(block)
            if text:
                content.append(text)
        # "thinking" blocks are dropped: the field is Anthropic-only, and a
        # chat/completions client has nowhere to display the reasoning.

    message: Dict[str, Any] = {
        "role": "assistant",
        # Null rather than an empty string when the turn was only tool calls —
        # that is what OpenAI sends, and clients branch on it.
        "content": "".join(content) or None,
        "refusal": None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": new_completion_id(body.get("id")),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": str(body.get("model") or model_name or ""),
        "choices": [
            {
                "index": 0,
                "message": message,
                "logprobs": None,
                "finish_reason": finish_reason(body.get("stop_reason"), saw_tool_call=bool(tool_calls)) or "stop",
            }
        ],
        "usage": openai_usage_block(body.get("usage")),
    }


class MessagesStreamTranslator:
    """Rewrites an Anthropic Messages SSE stream as a chat/completions one.

    Fed the upstream's bytes as they arrive and returns the bytes to forward.
    The direction is the easy one: Anthropic's stream is the stricter protocol
    — one content block open at a time, indices without gaps — and every event
    it defines maps onto a chat/completions delta that can go out immediately.
    Nothing has to be buffered to the end of the turn.

    The one piece of bookkeeping is the index space. Anthropic numbers every
    content block, text and tool calls alike, while OpenAI numbers tool calls
    among themselves — so a tool call in block 1 is ``tool_calls[0]``.
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._decoder = SSEDecoder()
        self._model = str(model_name or "")
        self._id = new_completion_id(None)
        self._created = int(time.time())
        self._opened = False
        self._finished = False
        # Anthropic content-block index -> OpenAI tool_calls index.
        self._tool_indices: Dict[int, int] = {}
        self._stop_reason: Optional[str] = None
        self._usage: Dict[str, Any] = {}

    def feed(self, chunk: Any) -> List[bytes]:
        out: List[bytes] = []
        for _, data in self._decoder.feed(chunk):
            out.extend(self._event(data))
        return out

    def finish(self) -> List[bytes]:
        """Close the stream: the terminal choice, the usage frame, ``[DONE]``.

        Idempotent, like its counterpart — a stream that already ended on
        ``message_stop`` has emitted all three, and this closes one that simply
        ran out of bytes.
        """
        if self._finished:
            return []
        out = self._open()
        self._finished = True
        out.append(
            self._chunk(
                {},
                finish=finish_reason(self._stop_reason, saw_tool_call=bool(self._tool_indices)) or "stop",
            )
        )
        # A separate usage frame with no choices, which is how chat/completions
        # reports it. Logos asks every chat/completions upstream for one (see
        # ``Executor._streaming_payload``), so its clients already see it.
        usage_frame = {
            "id": self._id,
            "object": "chat.completion.chunk",
            "created": self._created,
            "model": self._model,
            "choices": [],
            "usage": openai_usage_block(self._usage),
        }
        out.append(_sse(usage_frame))
        out.append(b"data: [DONE]\n\n")
        return out

    def error(self, message: str, error_type: str = "api_error") -> List[bytes]:
        """Report a mid-stream failure in the chat/completions protocol.

        An OpenAI client reads a ``data:`` frame carrying an ``error`` object,
        then the ``[DONE]`` that ends every stream. Nothing else may follow, so
        the terminal choice and usage frames are skipped.
        """
        if self._finished:
            return []
        self._finished = True
        body = {"error": {"message": str(message), "type": error_type}}
        return [_sse(body), b"data: [DONE]\n\n"]

    def _event(self, data: str) -> List[bytes]:
        payload = data.strip()
        if not payload:
            return []
        try:
            frame = json.loads(payload)
        except (TypeError, ValueError):
            return []
        if not isinstance(frame, dict):
            return []

        event = str(frame.get("type") or "")
        if event == "error":
            error = frame.get("error") if isinstance(frame.get("error"), dict) else {}
            return self.error(
                str(error.get("message") or "upstream stream error"),
                str(error.get("type") or "api_error"),
            )
        if event == "message_start":
            return self._message_start(frame)
        if event == "content_block_start":
            return self._block_start(frame)
        if event == "content_block_delta":
            return self._block_delta(frame)
        if event == "message_delta":
            delta = frame.get("delta") if isinstance(frame.get("delta"), dict) else {}
            if delta.get("stop_reason"):
                self._stop_reason = str(delta["stop_reason"])
            self._record_usage(frame.get("usage"))
            return []
        if event == "message_stop":
            return self.finish()
        # content_block_stop and ping carry nothing a chat/completions stream
        # can express: OpenAI has no block boundaries and no keepalive event.
        return []

    def _message_start(self, frame: Dict[str, Any]) -> List[bytes]:
        message = frame.get("message") if isinstance(frame.get("message"), dict) else {}
        self._id = new_completion_id(message.get("id"))
        self._model = str(message.get("model") or self._model)
        self._record_usage(message.get("usage"))
        return self._open()

    def _block_start(self, frame: Dict[str, Any]) -> List[bytes]:
        block = frame.get("content_block") if isinstance(frame.get("content_block"), dict) else {}
        if block.get("type") != "tool_use":
            return []
        index = _block_index(frame)
        if index is None:
            return []
        call_index = len(self._tool_indices)
        self._tool_indices[index] = call_index
        out = self._open()
        out.append(
            self._chunk(
                {
                    "tool_calls": [
                        {
                            "index": call_index,
                            "id": str(block.get("id") or ""),
                            "type": "function",
                            "function": {"name": str(block.get("name") or ""), "arguments": ""},
                        }
                    ]
                }
            )
        )
        return out

    def _block_delta(self, frame: Dict[str, Any]) -> List[bytes]:
        delta = frame.get("delta") if isinstance(frame.get("delta"), dict) else {}
        kind = delta.get("type")
        if kind == "text_delta":
            text = delta.get("text")
            if not isinstance(text, str) or not text:
                return []
            out = self._open()
            out.append(self._chunk({"content": text}))
            return out
        if kind == "input_json_delta":
            partial = delta.get("partial_json")
            index = _block_index(frame)
            call_index = self._tool_indices.get(index) if index is not None else None
            if call_index is None or not isinstance(partial, str) or not partial:
                return []
            out = self._open()
            out.append(self._chunk({"tool_calls": [{"index": call_index, "function": {"arguments": partial}}]}))
            return out
        # thinking_delta and signature_delta belong to a block that is dropped
        # from the translated answer, so their deltas are dropped with it.
        return []

    def _record_usage(self, usage: Any) -> None:
        """Merge an event's usage into the figures the final frame reports.

        Anthropic splits them across the stream: ``message_start`` states the
        prompt, ``message_delta`` settles the completion. Merging rather than
        replacing keeps both.
        """
        if isinstance(usage, dict):
            self._usage.update({key: value for key, value in usage.items() if value is not None})

    def _open(self) -> List[bytes]:
        """Emit the opening chunk once — the one that announces the role."""
        if self._opened or self._finished:
            return []
        self._opened = True
        return [self._chunk({"role": "assistant", "content": ""})]

    def _chunk(self, delta: Dict[str, Any], finish: Optional[str] = None) -> bytes:
        return _sse(
            {
                "id": self._id,
                "object": "chat.completion.chunk",
                "created": self._created,
                "model": self._model,
                "choices": [{"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish}],
            }
        )


def _block_index(frame: Dict[str, Any]) -> Optional[int]:
    """The content-block index an event refers to, if it states a usable one."""
    index = frame.get("index")
    return index if isinstance(index, int) and not isinstance(index, bool) else None


def _sse(data: Dict[str, Any]) -> bytes:
    """Encode one chat/completions SSE frame.

    Unlike Anthropic's, this protocol names no events — every frame is a bare
    ``data:`` line, and the stream ends on the ``[DONE]`` sentinel.
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
