"""Anthropic's server-side web search tool, run by Logos itself.

Claude Code's ``WebSearch`` (and any Anthropic SDK client) does not search on
its own: it sends a Messages request whose ``tools`` hold
``{"type": "web_search_20250305", "name": "web_search", ...}`` — no
``input_schema`` — and expects the API to run the searches and answer with
``server_tool_use`` and ``web_search_tool_result`` blocks next to the model's
text. No model Logos serves knows that tool, and vLLM rejects the definition
outright.

So Logos plays the part of the API here. The server tool becomes an ordinary
function tool for the model; whenever the model calls it, Logos searches
DuckDuckGo (``logos.web_search``) and hands the results back, until the model
answers or asks for one of the client's own tools. Every model turn goes
through the normal request pipeline, so routing, permissions, logging and
billing are those of any other request. The client receives the turns folded
into one message, shaped like Anthropic's: Claude Code reads the titles and
URLs from the ``web_search_tool_result`` blocks and the answer from the text.

A client that continues the conversation sends those blocks back; they are
turned into the ``tool_use`` / ``tool_result`` pair the model saw, with the
snippets recovered from ``encrypted_content``, which Logos fills itself.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from logos.anthropic_compat.common import error_body, new_message_id, sse
from logos.web_search import SearchUnavailable, search_web

SERVER_TOOL_TYPE_PREFIX = "web_search_"
# The searches one request may run when the client sets no max_uses. Each one
# costs a model turn, so a model that keeps searching is stopped well before
# it can tie up a lane for minutes.
DEFAULT_MAX_USES = 5
_MAX_RESULTS = 10
_MAX_QUERY_CHARS = 500

ModelCall = Callable[[Dict[str, Any]], Awaitable[Tuple[int, Any]]]


def server_web_search_tool(payload: Any) -> Optional[Dict[str, Any]]:
    """The web search server tool in a Messages request, if it carries one."""
    tools = payload.get("tools") if isinstance(payload, dict) else None
    for tool in tools if isinstance(tools, list) else []:
        if isinstance(tool, dict) and str(tool.get("type") or "").startswith(SERVER_TOOL_TYPE_PREFIX):
            return tool
    return None


def _model_tool(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "description": (
            "Search the web. Returns the title, URL and a snippet of each result. "
            "Search again with a different query if the results do not answer the question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The search query"}},
            "required": ["query"],
        },
    }


# ── results ─────────────────────────────────────────────────────────────────


def _encode_snippet(snippet: str) -> str:
    return base64.b64encode(snippet.encode()).decode()


def _decode_snippet(value: Any) -> str:
    try:
        return base64.b64decode(str(value or ""), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return ""  # Opaque content from somewhere else; the title and URL still count.


def _host_matches(url: str, domains: List[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    for domain in domains:
        domain = str(domain).lower().strip().removeprefix("www.").split("/")[0]
        if domain and (host == domain or host.endswith("." + domain)):
            return True
    return False


def _model_text(results: List[Dict[str, str]]) -> str:
    if not results:
        return "No results."
    return json.dumps(results, ensure_ascii=False)


async def _search(tool: Dict[str, Any], tool_input: Any) -> Tuple[Any, str]:
    """Run one search: the client's ``web_search_tool_result`` content, and the model's text."""
    query = tool_input.get("query") if isinstance(tool_input, dict) else None
    if not isinstance(query, str) or not query.strip():
        return {"type": "web_search_tool_result_error", "error_code": "invalid_tool_input"}, "Error: no query."
    query = query.strip()[:_MAX_QUERY_CHARS]
    allowed = [d for d in tool.get("allowed_domains") or [] if isinstance(d, str)]
    blocked = [d for d in tool.get("blocked_domains") or [] if isinstance(d, str)]
    if len(allowed) == 1:
        query = f"site:{allowed[0]} {query}"
    try:
        found = await search_web(query, _MAX_RESULTS)
    except SearchUnavailable as exc:
        return {"type": "web_search_tool_result_error", "error_code": "unavailable"}, f"Error: {exc}"
    results = [
        r
        for r in found
        if (not allowed or _host_matches(r["url"], allowed)) and not (blocked and _host_matches(r["url"], blocked))
    ]
    content = [
        {
            "type": "web_search_result",
            "title": r["title"],
            "url": r["url"],
            "encrypted_content": _encode_snippet(r.get("snippet", "")),
            "page_age": None,
        }
        for r in results
    ]
    return content, _model_text(results)


# ── history ─────────────────────────────────────────────────────────────────


def _blocks(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def _result_text(block: Dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, list):
        return _model_text(
            [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": _decode_snippet(r.get("encrypted_content")),
                }
                for r in content
                if isinstance(r, dict)
            ]
        )
    code = content.get("error_code") if isinstance(content, dict) else None
    return f"Error: {code or 'unavailable'}"


def history_for_model(messages: Any) -> List[Dict[str, Any]]:
    """Rewrite earlier server-tool blocks into the tool_use/tool_result pair the model saw.

    A ``web_search_tool_result`` sits inside the assistant message; for the
    model its ``tool_result`` has to come in a user turn of its own, so the
    assistant message is split there. Messages of the same role that end up
    next to each other are merged, keeping the turns alternating.
    """
    result: List[Dict[str, Any]] = []

    def emit(role: str, blocks: List[Dict[str, Any]]) -> None:
        if not blocks:
            return
        if result and result[-1]["role"] == role:
            result[-1]["content"] = result[-1]["content"] + blocks
        else:
            result.append({"role": role, "content": blocks})

    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role != "assistant":
            emit(str(role), _blocks(message.get("content")))
            continue
        pending: List[Dict[str, Any]] = []
        for block in _blocks(message.get("content")):
            kind = block.get("type")
            if kind == "server_tool_use":
                pending.append(
                    {
                        "type": "tool_use",
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input") or {},
                    }
                )
            elif kind == "web_search_tool_result":
                emit("assistant", pending)
                pending = []
                emit(
                    "user",
                    [{"type": "tool_result", "tool_use_id": block.get("tool_use_id"), "content": _result_text(block)}],
                )
            elif kind == "text":
                pending.append({"type": "text", "text": block.get("text", "")})  # without citations
            else:
                pending.append(block)
        emit("assistant", pending)
    return result


# ── the loop ────────────────────────────────────────────────────────────────


def _add_usage(total: Dict[str, int], usage: Any) -> None:
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = usage.get(key) if isinstance(usage, dict) else None
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value


def _server_id(tool_use_id: Any) -> str:
    suffix = str(tool_use_id or "").removeprefix("toolu_") or secrets.token_hex(12)
    return f"srvtoolu_{suffix}"


async def run(payload: Dict[str, Any], tool: Dict[str, Any], call_model: ModelCall) -> Tuple[int, Dict[str, Any]]:
    """Answer a Messages request carrying the web search server tool.

    ``call_model`` sends one non-streaming Messages request through the normal
    pipeline and returns its status and body. The result is a complete
    Anthropic message, or the error of the model turn that failed.
    """
    name = str(tool.get("name") or "web_search")
    max_uses = tool.get("max_uses") if isinstance(tool.get("max_uses"), int) else DEFAULT_MAX_USES
    max_uses = max(0, min(max_uses, DEFAULT_MAX_USES))
    client_tools = [t for t in payload.get("tools") or [] if isinstance(t, dict) and t is not tool]
    messages = history_for_model(payload.get("messages"))
    tool_choice = payload.get("tool_choice")

    content: List[Dict[str, Any]] = []
    usage: Dict[str, int] = {}
    searches = 0
    body: Dict[str, Any] = {}
    # One turn per search, plus the one that answers. A model that is still
    # calling the tool after that is cut off with what it has.
    for _ in range(max_uses + 2):
        request = {**payload, "messages": messages, "tools": client_tools + [_model_tool(name)], "stream": False}
        if tool_choice is not None:
            request["tool_choice"] = tool_choice
        else:
            request.pop("tool_choice", None)
        status, body = await call_model(request)
        if status != 200 or not isinstance(body, dict) or body.get("type") == "error":
            return status if status != 200 else 502, body if isinstance(body, dict) else error_body(str(body))
        _add_usage(usage, body.get("usage"))

        turn = _blocks(body.get("content"))
        own_calls = [b for b in turn if b.get("type") == "tool_use" and b.get("name") == name]
        own_ids = {id(b) for b in own_calls}
        results_for_model: List[Dict[str, Any]] = []
        for block in turn:
            if id(block) not in own_ids:
                content.append(block)
                continue
            server_id = _server_id(block.get("id"))
            content.append(
                {"type": "server_tool_use", "id": server_id, "name": name, "input": block.get("input") or {}}
            )
            if searches >= max_uses:
                result: Any = {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}
                text = "Error: the search limit for this request is reached. Answer with what you have."
            else:
                searches += 1
                result, text = await _search(tool, block.get("input"))
            content.append({"type": "web_search_tool_result", "tool_use_id": server_id, "content": result})
            results_for_model.append({"type": "tool_result", "tool_use_id": block.get("id"), "content": text})

        client_calls = any(b.get("type") == "tool_use" and b.get("name") != name for b in turn)
        if not own_calls or client_calls:
            break
        messages = messages + [{"role": "assistant", "content": turn}, {"role": "user", "content": results_for_model}]
        # A forced tool choice has done its job once the search ran; forcing
        # it again would never let the model answer.
        if isinstance(tool_choice, dict) and tool_choice.get("type") in ("any", "tool"):
            tool_choice = {"type": "auto"}

    stop_reason = body.get("stop_reason") or "end_turn"
    if stop_reason == "tool_use" and not any(b.get("type") == "tool_use" for b in content):
        stop_reason = "end_turn"  # cut off while still searching; nothing for the client to run
    final_usage: Dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, **usage}
    final_usage["server_tool_use"] = {"web_search_requests": searches}
    return 200, {
        "id": new_message_id(body.get("id")),
        "type": "message",
        "role": "assistant",
        "model": body.get("model") or payload.get("model"),
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": body.get("stop_sequence"),
        "usage": final_usage,
    }


# ── streaming ───────────────────────────────────────────────────────────────


def stream_start(message_id: str, model: Any) -> bytes:
    """``message_start``, sent before the first model turn so the stream is open while it runs."""
    return sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )


def stream_ping() -> bytes:
    return sse("ping", {"type": "ping"})


def stream_rest(message: Dict[str, Any]) -> List[bytes]:
    """Everything after ``message_start`` for a finished message."""
    out: List[bytes] = []
    for index, block in enumerate(message.get("content") or []):
        kind = block.get("type")
        if kind == "text":
            start, delta = {"type": "text", "text": ""}, {"type": "text_delta", "text": block.get("text", "")}
        elif kind == "thinking":
            start = {"type": "thinking", "thinking": "", "signature": ""}
            delta = {"type": "thinking_delta", "thinking": block.get("thinking", "")}
        elif kind in ("tool_use", "server_tool_use"):
            start = {**block, "input": {}}
            delta = {
                "type": "input_json_delta",
                "partial_json": json.dumps(block.get("input") or {}, ensure_ascii=False),
            }
        else:
            start, delta = block, None
        out.append(sse("content_block_start", {"type": "content_block_start", "index": index, "content_block": start}))
        if delta is not None:
            out.append(sse("content_block_delta", {"type": "content_block_delta", "index": index, "delta": delta}))
        if kind == "thinking" and block.get("signature"):
            out.append(
                sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "signature_delta", "signature": block["signature"]},
                    },
                )
            )
        out.append(sse("content_block_stop", {"type": "content_block_stop", "index": index}))
    out.append(
        sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": message.get("stop_reason"), "stop_sequence": message.get("stop_sequence")},
                "usage": message.get("usage") or {},
            },
        )
    )
    out.append(sse("message_stop", {"type": "message_stop"}))
    return out


def stream_error(status: int, body: Any) -> bytes:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return sse("error", error_body(str(error.get("message") or error), str(error.get("type") or "api_error")))
    return sse("error", error_body(f"Upstream request failed with HTTP {status}"))
