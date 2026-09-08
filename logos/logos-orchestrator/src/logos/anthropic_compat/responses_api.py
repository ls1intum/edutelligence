# src/logos/anthropic_compat/responses_api.py
"""Anthropic Messages ⇄ OpenAI Responses API.

The dialect the gpt-5.x reasoning family is addressed with. Logos already
stores those Azure deployments against a ``responses`` operation
(``classify_azure_operation``), so a Messages request routed to one of them
has to be translated into the Responses shape rather than chat/completions —
the deployment serves no other surface.

The Responses API differs from chat/completions in more than field names: the
conversation is a flat ``input`` list in which tool calls and their results are
top-level items rather than message attachments, and its event stream names
every event.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from logos.anthropic_compat.common import (
    AnthropicStreamWriter,
    SSEDecoder,
    anthropic_tools,
    image_data_url,
    json_arguments,
    new_message_id,
    normalize_content,
    parse_arguments,
    system_to_text,
    tool_result_text,
    usage_block,
)

# Usage keys Logos adds to a cloud response after the fact; see the same
# constant in chat_completions.py.
_LOGOS_USAGE_EXTRAS = ("cost", "cost_currency")


def to_responses(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Translate an Anthropic Messages request into a Responses request.

    ``temperature`` and ``top_p`` are deliberately not carried over: this
    dialect is only reached for reasoning deployments, which reject both, and
    Anthropic clients send a temperature on every request.
    """
    items: List[Dict[str, Any]] = []
    for message in payload.get("messages") or []:
        if isinstance(message, dict):
            items.extend(_translate_message(message))

    result: Dict[str, Any] = {
        "model": payload.get("model"),
        "input": items,
    }

    instructions = system_to_text(payload.get("system"))
    if instructions:
        result["instructions"] = instructions
    if payload.get("max_tokens") is not None:
        result["max_output_tokens"] = payload["max_tokens"]
    if payload.get("stream") is not None:
        result["stream"] = payload["stream"]

    tools = anthropic_tools(payload.get("tools"))
    if tools:
        result["tools"] = [{"type": "function", **tool} for tool in tools]
        choice = _tool_choice(payload.get("tool_choice"))
        if choice is not None:
            result["tool_choice"] = choice

    effort = _reasoning_effort(payload)
    if effort:
        result["reasoning"] = {"effort": effort}

    return result


def _translate_message(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One Anthropic message -> the Responses input items it becomes.

    Tool calls and tool results are siblings of the messages here, not fields
    on them, so an assistant turn that called two tools becomes one message
    item plus two ``function_call`` items.
    """
    role = message.get("role")
    blocks = normalize_content(message.get("content"))
    is_assistant = role == "assistant"

    items: List[Dict[str, Any]] = []
    parts: List[Dict[str, Any]] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            # ``input_text`` for every role, the assistant's own history
            # included. ``output_text`` belongs to an output item, which also
            # carries an ``id`` and a ``status`` this translation has nothing
            # to fill in — sending it without them can be rejected outright,
            # so a second turn that replays an assistant answer would 400.
            parts.append({"type": "input_text", "text": str(block.get("text") or "")})
        elif kind == "image" and not is_assistant:
            url = image_data_url(block)
            if url:
                parts.append({"type": "input_image", "image_url": url})
        elif kind == "tool_use":
            items.append(
                {
                    "type": "function_call",
                    "call_id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "arguments": json_arguments(block.get("input")),
                }
            )
        elif kind == "tool_result":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(block.get("tool_use_id") or ""),
                    "output": tool_result_text(block),
                }
            )

    if parts:
        # Tool results answer the previous turn's calls and must precede the
        # prose of the turn that carries them, exactly as in chat/completions.
        outputs = [item for item in items if item["type"] == "function_call_output"]
        calls = [item for item in items if item["type"] != "function_call_output"]
        message_item = {"type": "message", "role": role or "user", "content": parts}
        return [*outputs, message_item, *calls]
    return items


def _tool_choice(choice: Any) -> Any:
    """Anthropic ``tool_choice`` -> the Responses spelling."""
    if not isinstance(choice, dict):
        return None
    kind = choice.get("type")
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    if kind == "tool" and choice.get("name"):
        return {"type": "function", "name": str(choice["name"])}
    return None


def _reasoning_effort(payload: Dict[str, Any]) -> Optional[str]:
    """The reasoning effort a Messages request asks for, if any."""
    output_config = payload.get("output_config")
    if isinstance(output_config, dict) and output_config.get("effort"):
        return str(output_config["effort"])
    thinking = payload.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        return "medium"
    return None


# ── response ────────────────────────────────────────────────────────────────


def _stop_reason(body: Dict[str, Any], *, saw_tool_call: bool) -> str:
    """Anthropic stop reason for a finished Responses body.

    The Responses API reports completion as a status plus an
    ``incomplete_details.reason`` rather than a per-choice finish reason.
    """
    if saw_tool_call:
        return "tool_use"
    details = body.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, dict) else None
    if reason == "max_output_tokens" or body.get("status") == "incomplete":
        return "max_tokens"
    return "end_turn"


def _usage(body: Dict[str, Any]) -> Dict[str, Any]:
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    result = usage_block(
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        details.get("cached_tokens", 0),
    )
    for extra in _LOGOS_USAGE_EXTRAS:
        if extra in usage:
            result[extra] = usage[extra]
    return result


def from_response(body: Dict[str, Any], *, model_name: Optional[str] = None) -> Dict[str, Any]:
    """Translate a Responses body into an Anthropic message.

    ``reasoning`` items are dropped: their content is a provider-side summary
    with no Anthropic counterpart a client could echo back on the next turn.
    """
    content: List[Dict[str, Any]] = []
    saw_tool_call = False

    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text" and part.get("text"):
                    content.append({"type": "text", "text": str(part["text"])})
        elif kind == "function_call":
            saw_tool_call = True
            content.append(
                {
                    "type": "tool_use",
                    "id": str(item.get("call_id") or item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "input": parse_arguments(item.get("arguments")),
                }
            )

    return {
        "id": new_message_id(body.get("id")),
        "type": "message",
        "role": "assistant",
        "model": str(body.get("model") or model_name or ""),
        "content": content,
        "stop_reason": _stop_reason(body, saw_tool_call=saw_tool_call),
        "stop_sequence": None,
        "usage": _usage(body),
    }


class ResponsesStreamTranslator:
    """Rewrites a Responses SSE stream as an Anthropic Messages stream."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._decoder = SSEDecoder()
        self._model = str(model_name or "")
        self._writer: Optional[AnthropicStreamWriter] = None
        self._stop_reason: Optional[str] = None
        # Output index -> {"id", "name", "arguments"}, insertion-ordered.
        # Collected rather than relayed for the same reason as in the
        # chat/completions translator: one Anthropic content block is open at
        # a time, so a delta belonging to any other call would be dropped.
        self._tools: Dict[str, Dict[str, str]] = {}

    def feed(self, chunk: Any) -> List[bytes]:
        out: List[bytes] = []
        for name, data in self._decoder.feed(chunk):
            out.extend(self._event(name, data))
        return out

    def finish(self) -> List[bytes]:
        writer = self._ensure_writer()
        saw_tool_call = bool(self._tools)
        out = self._flush_tools(writer)
        out.extend(writer.stop(self._stop_reason or ("tool_use" if saw_tool_call else "end_turn")))
        return out

    def _flush_tools(self, writer: AnthropicStreamWriter) -> List[bytes]:
        """Write each collected function call as one complete content block."""
        out: List[bytes] = []
        for key, call in self._tools.items():
            out.extend(writer.tool_use(key, call["id"], call["name"]))
            out.extend(writer.tool_arguments(key, call["arguments"]))
        self._tools = {}
        return out

    def error(self, message: str, error_type: str = "api_error") -> List[bytes]:
        return self._ensure_writer().error(message, error_type)

    def _ensure_writer(self) -> AnthropicStreamWriter:
        if self._writer is None:
            self._writer = AnthropicStreamWriter(new_message_id(None), self._model)
        return self._writer

    def _event(self, name: Optional[str], data: str) -> List[bytes]:
        payload = data.strip()
        if not payload or payload == "[DONE]":
            return self.finish() if payload == "[DONE]" else []
        try:
            frame = json.loads(payload)
        except (TypeError, ValueError):
            return []
        if not isinstance(frame, dict):
            return []

        # The event name is authoritative; the payload repeats it in "type"
        # for clients that read only the data lines.
        event = name or str(frame.get("type") or "")

        if event in ("response.failed", "error"):
            # ``error`` is an object in the spec, but upstreams do send a bare
            # string; dropping that shape would replace the real cause with the
            # generic fallback. Same tolerance as the chat/completions
            # translator.
            raw_error = frame.get("error")
            error = raw_error if isinstance(raw_error, dict) else {}
            response = frame.get("response") if isinstance(frame.get("response"), dict) else {}
            nested = response.get("error") if isinstance(response.get("error"), dict) else {}
            message = (
                error.get("message")
                or (raw_error if isinstance(raw_error, str) else None)
                or nested.get("message")
                or "upstream stream error"
            )
            return self.error(str(message))

        if event == "response.created":
            response = frame.get("response") if isinstance(frame.get("response"), dict) else {}
            self._model = str(response.get("model") or self._model)
            self._writer = AnthropicStreamWriter(new_message_id(response.get("id")), self._model)
            return []

        writer = self._ensure_writer()

        if event == "response.output_item.added":
            item = frame.get("item") if isinstance(frame.get("item"), dict) else {}
            if item.get("type") == "function_call":
                entry = self._tools.setdefault(
                    str(frame.get("output_index", 0)), {"id": "", "name": "", "arguments": ""}
                )
                entry["id"] = str(item.get("call_id") or item.get("id") or "")
                entry["name"] = str(item.get("name") or "")
            return []

        if event == "response.output_text.delta":
            return writer.text(str(frame.get("delta") or ""))

        if event == "response.function_call_arguments.delta":
            key = str(frame.get("output_index", 0))
            entry = self._tools.setdefault(key, {"id": "", "name": "", "arguments": ""})
            entry["arguments"] += str(frame.get("delta") or "")
            return []

        if event in ("response.completed", "response.incomplete"):
            response = frame.get("response") if isinstance(frame.get("response"), dict) else {}
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
            writer.record_usage(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cached_tokens=details.get("cached_tokens"),
            )
            self._stop_reason = _stop_reason(response, saw_tool_call=bool(self._tools))
            return self.finish()

        return []
