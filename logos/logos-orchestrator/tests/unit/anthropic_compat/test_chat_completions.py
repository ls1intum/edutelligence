"""Anthropic Messages ⇄ chat/completions.

Covers the shapes Claude Code actually sends — a system prompt as a block
list, a tool call answered by a tool result, images — plus the streaming
protocol, whose event ordering clients parse strictly.
"""

import json

from logos.anthropic_compat.chat_completions import (
    ChatCompletionsStreamTranslator,
    from_chat_completion,
    to_chat_completions,
)


def _events(chunks):
    """Parse an emitted Anthropic SSE stream into ``(event, data)`` pairs."""
    text = b"".join(chunks).decode()
    out = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        out.append((name, data))
    return out


# ── request ─────────────────────────────────────────────────────────────────


def test_system_blocks_become_a_leading_system_message():
    # Claude Code sends `system` as a list of text blocks, one per section.
    result = to_chat_completions(
        {
            "model": "gpt-4.1-nano",
            "max_tokens": 64,
            "system": [{"type": "text", "text": "You are Claude Code."}, {"type": "text", "text": "Be brief."}],
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    assert result["messages"][0] == {"role": "system", "content": "You are Claude Code.\n\nBe brief."}
    assert result["messages"][1] == {"role": "user", "content": "hi"}
    assert result["max_tokens"] == 64


def test_reasoning_models_get_max_completion_tokens():
    # OpenAI and Azure reject max_tokens for the o-series and gpt-5 family.
    result = to_chat_completions({"model": "gpt-5.6-luna", "max_tokens": 64, "messages": []})
    assert result["max_completion_tokens"] == 64
    assert "max_tokens" not in result


def test_top_k_and_metadata_are_dropped():
    # Both are Anthropic-only; forwarding either is a 400.
    result = to_chat_completions(
        {
            "model": "m",
            "max_tokens": 8,
            "top_k": 40,
            "metadata": {"user_id": "u"},
            "temperature": 0.3,
            "stop_sequences": ["END"],
            "messages": [],
        }
    )
    assert "top_k" not in result and "metadata" not in result
    assert result["temperature"] == 0.3
    assert result["stop"] == ["END"]


def test_tool_call_and_result_become_tool_calls_and_tool_messages():
    result = to_chat_completions(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [
                {"role": "user", "content": "list files"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Running it."},
                        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "a.py"},
                        {"type": "text", "text": "and now?"},
                    ],
                },
            ],
        }
    )
    assistant = result["messages"][1]
    assert assistant["content"] == "Running it."
    assert assistant["tool_calls"] == [
        {"id": "toolu_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    ]
    # The tool result must precede the prose of the same turn: chat/completions
    # requires every tool message to follow the assistant call directly.
    assert result["messages"][2] == {"role": "tool", "tool_call_id": "toolu_1", "content": "a.py"}
    assert result["messages"][3] == {"role": "user", "content": "and now?"}


def test_thinking_blocks_are_dropped_from_assistant_history():
    # Their signature means nothing to an OpenAI upstream.
    result = to_chat_completions(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                        {"type": "text", "text": "answer"},
                    ],
                }
            ],
        }
    )
    assert result["messages"][0] == {"role": "assistant", "content": "answer"}


def test_base64_image_becomes_a_data_uri():
    result = to_chat_completions(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this?"},
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
                        },
                    ],
                }
            ],
        }
    )
    assert result["messages"][0]["content"] == [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]


def test_tools_and_tool_choice_are_translated():
    result = to_chat_completions(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [],
            "tools": [
                {"name": "Bash", "description": "run", "input_schema": {"type": "object"}},
                # Server-side tools carry no input_schema and have no OpenAI form.
                {"type": "web_search_20250305", "name": "web_search"},
            ],
            "tool_choice": {"type": "tool", "name": "Bash"},
        }
    )
    assert result["tools"] == [
        {"type": "function", "function": {"name": "Bash", "description": "run", "parameters": {"type": "object"}}}
    ]
    assert result["tool_choice"] == {"type": "function", "function": {"name": "Bash"}}


def test_effort_is_carried_over_for_the_normalizer_to_clamp():
    # normalize_reasoning_effort runs after this and owns the value itself.
    result = to_chat_completions({"model": "m", "max_tokens": 8, "messages": [], "output_config": {"effort": "high"}})
    assert result["reasoning_effort"] == "high"


# ── response ────────────────────────────────────────────────────────────────


def test_plain_answer_becomes_an_anthropic_message():
    result = from_chat_completion(
        {
            "id": "chatcmpl-1",
            "model": "gpt-4.1-nano",
            "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 18, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 8}},
        }
    )
    assert result["id"] == "msg_chatcmpl-1"
    assert result["type"] == "message"
    assert result["content"] == [{"type": "text", "text": "OK"}]
    assert result["stop_reason"] == "end_turn"
    assert result["usage"] == {
        "input_tokens": 18,
        "output_tokens": 2,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 8,
    }


def test_tool_call_response_reports_tool_use():
    result = from_chat_completion(
        {
            "id": "chatcmpl-2",
            "model": "m",
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [{"id": "call_1", "function": {"name": "Bash", "arguments": '{"command":"ls"}'}}],
                    },
                    # Some upstreams still say "stop" on a tool call; a client
                    # that reads end_turn there stops the agent loop.
                    "finish_reason": "stop",
                }
            ],
        }
    )
    assert result["stop_reason"] == "tool_use"
    assert result["content"] == [{"type": "tool_use", "id": "call_1", "name": "Bash", "input": {"command": "ls"}}]


def test_unparsable_tool_arguments_are_preserved_not_dropped():
    result = from_chat_completion(
        {
            "id": "c",
            "model": "m",
            "choices": [
                {
                    "message": {"tool_calls": [{"id": "c1", "function": {"name": "T", "arguments": '{"a":'}}]},
                    "finish_reason": "tool_calls",
                }
            ],
        }
    )
    assert result["content"][0]["input"] == {"_raw": '{"a":'}


def test_length_stop_maps_to_max_tokens():
    result = from_chat_completion(
        {"id": "c", "model": "m", "choices": [{"message": {"content": "x"}, "finish_reason": "length"}]}
    )
    assert result["stop_reason"] == "max_tokens"


def test_logos_cost_survives_the_translation():
    # The native Messages path surfaces the cost Logos computes for a cloud
    # response; the translated path has to as well.
    result = from_chat_completion(
        {
            "id": "c",
            "model": "m",
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.42, "cost_currency": "EUR"},
        }
    )
    assert result["usage"]["cost"] == 0.42
    assert result["usage"]["cost_currency"] == "EUR"


# ── streaming ───────────────────────────────────────────────────────────────


def _sse(payload):
    return f"data: {json.dumps(payload)}\n\n".encode()


def test_text_stream_emits_the_full_anthropic_event_sequence():
    translator = ChatCompletionsStreamTranslator("m")
    out = []
    out += translator.feed(_sse({"id": "chatcmpl-9", "model": "m", "choices": [{"delta": {"content": "He"}}]}))
    out += translator.feed(_sse({"choices": [{"delta": {"content": "llo"}}]}))
    out += translator.feed(_sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
    out += translator.feed(_sse({"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}))
    out += translator.feed(b"data: [DONE]\n\n")

    events = _events(out)
    assert [name for name, _ in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert events[0][1]["message"]["id"] == "msg_chatcmpl-9"
    assert "".join(e[1]["delta"]["text"] for e in events if e[0] == "content_block_delta") == "Hello"
    assert events[-2][1]["delta"]["stop_reason"] == "end_turn"
    assert events[-2][1]["usage"]["output_tokens"] == 2


def test_stream_splits_across_arbitrary_byte_boundaries():
    # Chunks arrive wherever the transport happens to cut them.
    translator = ChatCompletionsStreamTranslator("m")
    raw = _sse({"id": "c", "model": "m", "choices": [{"delta": {"content": "hi"}}]})
    out = translator.feed(raw[:9]) + translator.feed(raw[9:]) + translator.finish()
    assert "".join(e[1]["delta"]["text"] for e in _events(out) if e[0] == "content_block_delta") == "hi"


def test_tool_call_stream_becomes_a_tool_use_block():
    translator = ChatCompletionsStreamTranslator("m")
    out = []
    out += translator.feed(
        _sse(
            {
                "id": "c",
                "model": "m",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "Bash", "arguments": ""}}]
                        }
                    }
                ],
            }
        )
    )
    out += translator.feed(
        _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"cmd"'}}]}}]})
    )
    out += translator.feed(
        _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ':"ls"}'}}]}}]})
    )
    out += translator.feed(_sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}))
    out += translator.feed(b"data: [DONE]\n\n")

    events = _events(out)
    start = next(data for name, data in events if name == "content_block_start")
    assert start["content_block"] == {"type": "tool_use", "id": "call_1", "name": "Bash", "input": {}}
    partial = "".join(d["delta"]["partial_json"] for n, d in events if n == "content_block_delta")
    assert json.loads(partial) == {"cmd": "ls"}
    assert next(d for n, d in events if n == "message_delta")["delta"]["stop_reason"] == "tool_use"


def test_text_then_tool_call_uses_two_content_blocks_in_order():
    translator = ChatCompletionsStreamTranslator("m")
    out = translator.feed(_sse({"id": "c", "model": "m", "choices": [{"delta": {"content": "sure"}}]}))
    out += translator.feed(
        _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "t1", "function": {"name": "T"}}]}}]})
    )
    out += translator.finish()
    indices = [(n, d.get("index")) for n, d in _events(out) if n and n.startswith("content_block")]
    assert indices == [
        ("content_block_start", 0),
        ("content_block_delta", 0),
        ("content_block_stop", 0),
        ("content_block_start", 1),
        ("content_block_stop", 1),
    ]


def test_finish_is_idempotent():
    # [DONE] already closed the stream; the generator calls finish() again when
    # the upstream bytes run out.
    translator = ChatCompletionsStreamTranslator("m")
    translator.feed(_sse({"id": "c", "model": "m", "choices": [{"delta": {"content": "x"}}]}))
    first = translator.feed(b"data: [DONE]\n\n")
    assert [name for name, _ in _events(first)][-1] == "message_stop"
    assert translator.finish() == []


def test_midstream_failure_becomes_an_anthropic_error_event():
    translator = ChatCompletionsStreamTranslator("m")
    translator.feed(_sse({"id": "c", "model": "m", "choices": [{"delta": {"content": "x"}}]}))
    events = _events(translator.error("connection reset"))
    # The open block is closed, then error — and no message_stop, which would
    # read as a completed turn.
    assert [name for name, _ in events] == ["content_block_stop", "error"]
    assert events[-1][1]["error"]["message"] == "connection reset"


def test_multibyte_character_split_across_chunks_survives():
    # A transport chunk can end in the middle of a UTF-8 character. Decoding
    # each chunk on its own turns "ü" into replacement characters before the
    # translation ever sees it. Upstreams that emit raw UTF-8 rather than
    # \u-escapes (vLLM among them) are what makes this reachable.
    translator = ChatCompletionsStreamTranslator("m")
    frame = json.dumps({"id": "c", "model": "m", "choices": [{"delta": {"content": "Grüße 🎉"}}]}, ensure_ascii=False)
    raw = f"data: {frame}\n\n".encode()
    split = raw.index("ü".encode()) + 1  # mid-character
    out = translator.feed(raw[:split]) + translator.feed(raw[split:]) + translator.finish()
    assert "".join(e[1]["delta"]["text"] for e in _events(out) if e[0] == "content_block_delta") == "Grüße 🎉"


def test_streaming_switch_is_forwarded_without_stream_options():
    # include_usage is added by Executor._streaming_payload for every
    # non-Responses forward URL; setting it here too would only duplicate it.
    result = to_chat_completions({"model": "m", "max_tokens": 8, "messages": [], "stream": True})
    assert result["stream"] is True
    assert "stream_options" not in result
