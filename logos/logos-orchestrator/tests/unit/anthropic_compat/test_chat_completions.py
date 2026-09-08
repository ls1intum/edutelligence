"""Anthropic Messages ⇄ chat/completions.

Covers the shapes Claude Code actually sends — a system prompt as a block
list, a tool call answered by a tool result, images — plus the streaming
protocol, whose event ordering clients parse strictly.
"""

import json

import pytest

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


def test_effort_reaches_a_reasoning_model_for_the_normalizer_to_clamp():
    # normalize_reasoning_effort runs after this and owns the value itself.
    result = to_chat_completions(
        {"model": "gpt-5.6-luna", "max_tokens": 8, "messages": [], "output_config": {"effort": "high"}}
    )
    assert result["reasoning_effort"] == "high"


def test_the_two_openai_families_get_mutually_exclusive_parameters():
    """Sending both sets is a 400 on one family or the other.

    gpt-4.1 and every other older deployment reject ``reasoning_effort`` as an
    unrecognised argument; the o-series and gpt-5 reject ``temperature`` and
    ``top_p``. Claude Code supplies an effort on every request and a
    temperature routinely, so this cannot be left to the client.
    """
    request = {
        "max_tokens": 8,
        "messages": [],
        "system": "Be brief.",
        "temperature": 0.3,
        "top_p": 0.9,
        "stop_sequences": ["END"],
        "output_config": {"effort": "high"},
    }

    older = to_chat_completions({**request, "model": "gpt-4.1-nano"})
    assert older["temperature"] == 0.3 and older["top_p"] == 0.9
    assert older["max_tokens"] == 8
    assert older["stop"] == ["END"]
    assert older["messages"][0] == {"role": "system", "content": "Be brief."}
    assert "reasoning_effort" not in older

    for name in ("gpt-5.6-luna", "o1", "o3-mini", "openai/gpt-5.1"):
        reasoning = to_chat_completions({**request, "model": name})
        assert reasoning["reasoning_effort"] == "high", name
        assert reasoning["max_completion_tokens"] == 8, name
        assert "temperature" not in reasoning and "top_p" not in reasoning, name
        assert "max_tokens" not in reasoning, name
        # o3, o4-mini and the models after them reject stop sequences.
        assert "stop" not in reasoning, name
        # o1 and its successors replaced the system role with "developer" and
        # reject a system-role message outright — and Claude Code sends a
        # system prompt on every turn.
        assert reasoning["messages"][0] == {"role": "developer", "content": "Be brief."}, name


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


def _tool_inputs(events):
    """Reassemble each streamed tool_use block into its parsed input."""
    collected: dict[str, str] = {}
    current = None
    for name, data in events:
        if name == "content_block_start" and data["content_block"]["type"] == "tool_use":
            current = data["content_block"]["id"]
            collected.setdefault(current, "")
        elif name == "content_block_delta" and data["delta"].get("type") == "input_json_delta":
            collected[current] += data["delta"]["partial_json"]
    return {tool: json.loads(raw) for tool, raw in collected.items()}


def _tool_delta(index, *, call_id=None, name=None, arguments=None):
    call = {"index": index, "function": {}}
    if call_id:
        call["id"] = call_id
    if name:
        call["function"]["name"] = name
    if arguments is not None:
        call["function"]["arguments"] = arguments
    return _sse({"choices": [{"delta": {"tool_calls": [call]}}]})


def test_interleaved_parallel_tool_arguments_are_not_lost():
    """A fragment for a call that is not the open block must still land.

    Only one Anthropic content block is open at a time. Relaying fragments as
    they arrive dropped everything belonging to any other call — silently, and
    what reached the client was truncated JSON it would have handed to the
    tool.
    """
    translator = ChatCompletionsStreamTranslator("m")
    out = translator.feed(_sse({"id": "c", "model": "m", "choices": [{"delta": {"role": "assistant"}}]}))
    out += translator.feed(_tool_delta(0, call_id="call_0", name="Bash", arguments='{"cmd":'))
    out += translator.feed(_tool_delta(1, call_id="call_1", name="Read", arguments='{"path":"a"}'))
    out += translator.feed(_tool_delta(0, arguments='"ls"}'))
    out += translator.feed(_sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}))
    out += translator.feed(b"data: [DONE]\n\n")

    events = _events(out)
    assert _tool_inputs(events) == {"call_0": {"cmd": "ls"}, "call_1": {"path": "a"}}
    assert next(d for n, d in events if n == "message_delta")["delta"]["stop_reason"] == "tool_use"


def test_parallel_tool_blocks_keep_the_order_the_model_produced():
    translator = ChatCompletionsStreamTranslator("m")
    out = translator.feed(_sse({"id": "c", "model": "m", "choices": [{"delta": {"role": "assistant"}}]}))
    out += translator.feed(_tool_delta(0, call_id="first", name="A", arguments="{}"))
    out += translator.feed(_tool_delta(1, call_id="second", name="B", arguments="{}"))
    out += translator.finish()

    starts = [d["content_block"] for n, d in _events(out) if n == "content_block_start"]
    assert [block["id"] for block in starts] == ["first", "second"]
    assert [block["name"] for block in starts] == ["A", "B"]


def test_text_still_streams_while_tool_calls_are_collected():
    """Only tool arguments wait; prose is relayed as it arrives."""
    translator = ChatCompletionsStreamTranslator("m")
    first = translator.feed(_sse({"id": "c", "model": "m", "choices": [{"delta": {"content": "thinking"}}]}))
    assert [name for name, _ in _events(first)] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
    ]

    rest = translator.feed(_tool_delta(0, call_id="t", name="A", arguments="{}")) + translator.finish()
    names = [name for name, _ in _events(rest)]
    # The text block is closed before the tool block opens, and the tool block
    # is complete before the terminal events.
    assert names == [
        "content_block_stop",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]


@pytest.mark.parametrize("finish_reason", [None, "stop"])
def test_a_turn_that_ends_in_a_tool_call_always_reports_tool_use(finish_reason):
    """The stop reason must survive the tool flush.

    Not every upstream sends ``finish_reason: tool_calls`` — some send ``stop``,
    some send nothing before the stream ends. A client that reads ``end_turn``
    there stops the agent loop instead of running the tool.
    """
    translator = ChatCompletionsStreamTranslator("m")
    translator.feed(_sse({"id": "c", "model": "m", "choices": [{"delta": {"role": "assistant"}}]}))
    translator.feed(_tool_delta(0, call_id="t1", name="Bash", arguments="{}"))
    if finish_reason:
        translator.feed(_sse({"choices": [{"delta": {}, "finish_reason": finish_reason}]}))
    out = translator.finish()

    assert next(d for n, d in _events(out) if n == "message_delta")["delta"]["stop_reason"] == "tool_use"


def test_no_content_is_emitted_after_a_mid_stream_error():
    """The error event is terminal — nothing may follow it.

    Buffered tool calls outlive the failure, and the HTTP generator calls
    finish() after feeding the last chunk, so without a gate a tool block (and
    even message_start, when nothing had been emitted yet) would appear after
    the error and make a failed turn look like a completed one.
    """
    translator = ChatCompletionsStreamTranslator("m")
    translator.feed(_sse({"id": "c", "model": "m", "choices": [{"delta": {"role": "assistant"}}]}))
    translator.feed(_tool_delta(0, call_id="t1", name="Bash", arguments="{}"))

    events = _events(translator.error("connection reset"))
    assert [name for name, _ in events] == ["error"]
    # Whatever the caller does next must stay silent.
    assert translator.finish() == []
    assert translator.feed(_tool_delta(0, arguments='{"more":1}')) == []


def test_an_error_before_any_output_emits_only_the_error():
    translator = ChatCompletionsStreamTranslator("m")
    events = _events(translator.error("upstream gone"))
    assert [name for name, _ in events] == ["error"]
    assert translator.finish() == []
