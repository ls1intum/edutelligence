# src/logos/anthropic_compat/chat_completions.py
"""Anthropic Messages ⇄ OpenAI Chat Completions.

The dialect nearly every OpenAI-shaped upstream serves: Azure chat
deployments, OpenAI itself, DeepSeek, Groq and the OpenAI-compatible fronts of
other vendors. A Messages request is rewritten into a chat/completions request
on the way out and the answer — one JSON body or a stream of SSE events — is
rewritten back into the Messages shape on the way in.
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
    stop_reason,
    system_to_text,
    tool_result_text,
    usage_block,
    wants_max_completion_tokens,
)

# Sampling parameters that carry over unchanged. ``top_k`` is deliberately
# absent: chat/completions has no equivalent, and forwarding it is a 400 on
# OpenAI and Azure.
_PASSTHROUGH_PARAMS = ("temperature", "top_p")

# Usage keys Logos adds to a cloud response after the fact. They are not part
# of either API, but the native Messages path surfaces them, so the translated
# path has to as well or a cloud model's cost silently disappears for clients
# that reach it through /v1/messages.
_LOGOS_USAGE_EXTRAS = ("cost", "cost_currency")


def to_chat_completions(payload: Dict[str, Any], *, model_name: Optional[str] = None) -> Dict[str, Any]:
    """Translate an Anthropic Messages request into a chat/completions one.

    Only fields with a chat/completions counterpart are carried over — an
    unknown field is a 400 from OpenAI and Azure, so Anthropic-only fields
    (``metadata``, ``top_k``, server-side tools) are dropped rather than
    forwarded.
    """
    messages: List[Dict[str, Any]] = []

    system = system_to_text(payload.get("system"))
    if system:
        messages.append({"role": "system", "content": system})

    for message in payload.get("messages") or []:
        if isinstance(message, dict):
            messages.extend(_translate_message(message))

    result: Dict[str, Any] = {
        "model": payload.get("model"),
        "messages": messages,
    }

    max_tokens = payload.get("max_tokens")
    if max_tokens is not None:
        key = (
            "max_completion_tokens" if wants_max_completion_tokens(model_name or payload.get("model")) else "max_tokens"
        )
        result[key] = max_tokens

    for name in _PASSTHROUGH_PARAMS:
        if payload.get(name) is not None:
            result[name] = payload[name]

    if payload.get("stop_sequences"):
        result["stop"] = payload["stop_sequences"]
    if payload.get("stream") is not None:
        # Only the switch itself. ``stream_options.include_usage`` — which a
        # chat/completions upstream needs before it reports token counts — is
        # added by ``Executor._streaming_payload`` for every non-Responses
        # forward URL, which is where a translated Messages request goes.
        result["stream"] = payload["stream"]

    tools = anthropic_tools(payload.get("tools"))
    if tools:
        result["tools"] = [{"type": "function", "function": tool} for tool in tools]
        choice = _tool_choice(payload.get("tool_choice"))
        if choice is not None:
            result["tool_choice"] = choice

    effort = _reasoning_effort(payload)
    if effort:
        result["reasoning_effort"] = effort

    return result


def _translate_message(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One Anthropic message -> the chat/completions messages it becomes.

    Usually one, but a user turn that answers tool calls becomes several: the
    Messages API packs every ``tool_result`` into a single user message, while
    chat/completions wants one ``role: tool`` message per call, and those must
    precede any prose the same turn also carried.
    """
    role = message.get("role")
    blocks = normalize_content(message.get("content"))

    if role == "assistant":
        return _assistant_message(blocks)

    tool_messages: List[Dict[str, Any]] = []
    parts: List[Dict[str, Any]] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "tool_result":
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(block.get("tool_use_id") or ""),
                    "content": tool_result_text(block),
                }
            )
        elif kind == "text":
            parts.append({"type": "text", "text": str(block.get("text") or "")})
        elif kind == "image":
            url = image_data_url(block)
            if url:
                parts.append({"type": "image_url", "image_url": {"url": url}})
        elif kind == "document":
            # No chat/completions counterpart. Carrying the extracted text is
            # closer to the client's intent than dropping the block entirely.
            source = block.get("source") if isinstance(block.get("source"), dict) else {}
            text = str(source.get("data") or "") if source.get("type") == "text" else ""
            if text:
                parts.append({"type": "text", "text": text})

    if not parts:
        return tool_messages

    # A turn that is nothing but prose stays a plain string: some upstreams
    # (and every text-only model) reject the multimodal list form.
    only_text = all(part["type"] == "text" for part in parts)
    content: Any = "\n".join(part["text"] for part in parts) if only_text else parts
    return [*tool_messages, {"role": role or "user", "content": content}]


def _assistant_message(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assistant blocks -> one chat/completions assistant message.

    ``thinking`` blocks are dropped: they are Anthropic-only, and their
    signature is meaningless to an OpenAI upstream.
    """
    text_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            text_parts.append(str(block.get("text") or ""))
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

    message: Dict[str, Any] = {"role": "assistant", "content": "\n".join(part for part in text_parts if part)}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return [message]


def _tool_choice(choice: Any) -> Any:
    """Anthropic ``tool_choice`` -> the chat/completions spelling."""
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
        return {"type": "function", "function": {"name": str(choice["name"])}}
    return None


def _reasoning_effort(payload: Dict[str, Any]) -> Optional[str]:
    """The reasoning effort a Messages request asks for, if any.

    Claude Code sends it as ``output_config.effort``; the Messages API's own
    spelling is a ``thinking`` budget, which has no OpenAI counterpart beyond
    "reasoning is on". Values are not normalised here — the payload passes
    through ``normalize_reasoning_effort`` afterwards, which owns that.
    """
    output_config = payload.get("output_config")
    if isinstance(output_config, dict) and output_config.get("effort"):
        return str(output_config["effort"])
    thinking = payload.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        return "medium"
    return None


# ── response ────────────────────────────────────────────────────────────────


def from_chat_completion(body: Dict[str, Any], *, model_name: Optional[str] = None) -> Dict[str, Any]:
    """Translate a chat/completions response body into an Anthropic message."""
    choices = body.get("choices") if isinstance(body, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    message = message if isinstance(message, dict) else {}

    content: List[Dict[str, Any]] = []
    text = message.get("content")
    if isinstance(text, list):
        # Some upstreams answer in the multimodal list form even for plain text.
        text = "".join(part.get("text") or "" for part in text if isinstance(part, dict))
    if text:
        content.append({"type": "text", "text": str(text)})

    tool_calls = message.get("tool_calls")
    for call in tool_calls if isinstance(tool_calls, list) else []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        content.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or ""),
                "name": str(function.get("name") or ""),
                "input": parse_arguments(function.get("arguments")),
            }
        )

    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    result_usage = usage_block(
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        details.get("cached_tokens", 0),
    )
    for extra in _LOGOS_USAGE_EXTRAS:
        if extra in usage:
            result_usage[extra] = usage[extra]

    return {
        "id": new_message_id(body.get("id")),
        "type": "message",
        "role": "assistant",
        "model": str(body.get("model") or model_name or ""),
        "content": content,
        "stop_reason": stop_reason(choice.get("finish_reason"), saw_tool_call=bool(tool_calls)),
        "stop_sequence": None,
        "usage": result_usage,
    }


class ChatCompletionsStreamTranslator:
    """Rewrites a chat/completions SSE stream as an Anthropic Messages stream.

    Fed the upstream's bytes as they arrive and returns the Anthropic bytes to
    forward. Text is relayed as it arrives; tool calls are the exception and
    are held until the turn ends — see :meth:`_tool_call`.
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._decoder = SSEDecoder()
        self._model = str(model_name or "")
        self._writer: Optional[AnthropicStreamWriter] = None
        self._finish_reason: Optional[str] = None
        # Upstream tool-call index -> {"id", "name", "arguments"}, in the order
        # the indices first appeared. Insertion-ordered, so the blocks come out
        # in the order the model produced them.
        self._tools: Dict[str, Dict[str, str]] = {}

    def feed(self, chunk: Any) -> List[bytes]:
        out: List[bytes] = []
        for _, data in self._decoder.feed(chunk):
            out.extend(self._event(data))
        return out

    def finish(self) -> List[bytes]:
        """Emit the collected tool calls, then close the Anthropic stream."""
        writer = self._ensure_writer()
        # Read before flushing — _flush_tools empties the collection, and the
        # stop reason has to know the turn ended in a tool call.
        saw_tool_call = bool(self._tools)
        out = self._flush_tools(writer)
        out.extend(writer.stop(stop_reason(self._finish_reason, saw_tool_call=saw_tool_call)))
        return out

    def _flush_tools(self, writer: AnthropicStreamWriter) -> List[bytes]:
        """Write each collected tool call as one complete content block."""
        out: List[bytes] = []
        for key, call in self._tools.items():
            out.extend(writer.tool_use(key, call["id"], call["name"]))
            out.extend(writer.tool_arguments(key, call["arguments"]))
        self._tools = {}
        return out

    def error(self, message: str, error_type: str = "api_error") -> List[bytes]:
        """Report a mid-stream failure in the Anthropic protocol."""
        return self._ensure_writer().error(message, error_type)

    def _ensure_writer(self) -> AnthropicStreamWriter:
        if self._writer is None:
            self._writer = AnthropicStreamWriter(new_message_id(None), self._model)
        return self._writer

    def _event(self, data: str) -> List[bytes]:
        payload = data.strip()
        if not payload:
            return []
        if payload == "[DONE]":
            return self.finish()
        try:
            frame = json.loads(payload)
        except (TypeError, ValueError):
            return []
        if not isinstance(frame, dict):
            return []

        # An upstream that fails mid-stream sends an error frame rather than
        # closing the connection; Logos itself appends one when its own
        # forwarding breaks. Either way the turn did not complete.
        if isinstance(frame.get("error"), (dict, str)):
            error = frame["error"]
            message = error.get("message") if isinstance(error, dict) else error
            return self.error(str(message or "upstream stream error"))

        if self._writer is None:
            self._model = str(frame.get("model") or self._model)
            self._writer = AnthropicStreamWriter(new_message_id(frame.get("id")), self._model)
        writer = self._writer

        usage = frame.get("usage")
        if isinstance(usage, dict):
            details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
            writer.record_usage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                cached_tokens=details.get("cached_tokens"),
            )

        choices = frame.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else None
        if not isinstance(choice, dict):
            return []

        out: List[bytes] = []
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        text = delta.get("content")
        if isinstance(text, str) and text:
            out.extend(writer.text(text))

        for call in delta.get("tool_calls") or []:
            if isinstance(call, dict):
                self._tool_call(call)

        if choice.get("finish_reason"):
            self._finish_reason = str(choice["finish_reason"])
        return out

    def _tool_call(self, call: Dict[str, Any]) -> None:
        """Collect one tool-call delta; nothing is emitted yet.

        The Anthropic protocol keeps exactly one content block open at a time,
        while chat/completions may interleave the deltas of parallel tool calls
        by index. Relaying them as they arrive therefore drops every fragment
        that belongs to a call other than the one currently open — silently, and
        what is left is truncated JSON that the client hands to the tool. So the
        fragments are accumulated per index and written out as whole blocks in
        :meth:`finish`. Only the first delta of a call carries its id and name.
        """
        key = str(call.get("index", 0))
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        entry = self._tools.setdefault(key, {"id": "", "name": "", "arguments": ""})
        if call.get("id"):
            entry["id"] = str(call["id"])
        if function.get("name"):
            entry["name"] = str(function["name"])
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            entry["arguments"] += arguments
