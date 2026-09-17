"""chat/completions ⇄ Anthropic Messages.

The direction that serves an OpenAI client from a Claude deployment. What is
pinned here is mostly the set of things that are a 400 on the Messages API
rather than a lossy translation: a missing ``max_tokens``, an OpenAI tool
schema, an empty content block, two user turns in a row.
"""

import json

from logos.anthropic_compat.messages_api import MessagesStreamTranslator, from_message, to_messages
from logos.context_budget import DEFAULT_OUTPUT_RESERVE_TOKENS


def _frames(chunks):
    """Parse an emitted chat/completions SSE stream into its JSON frames."""
    text = b"".join(chunks).decode()
    out = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data: "), block
        payload = block[len("data: ") :]
        out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


def _deltas(frames):
    """The ``delta`` of every frame that carries a choice."""
    return [frame["choices"][0]["delta"] for frame in frames if frame != "[DONE]" and frame["choices"]]


# ── request ─────────────────────────────────────────────────────────────────


def test_system_turns_are_hoisted_out_of_the_conversation():
    # OpenAI allows a system turn anywhere; Anthropic has one system field and
    # only user/assistant roles in ``messages``.
    result = to_messages(
        {
            "model": "claude-opus-5",
            "max_tokens": 64,
            "messages": [
                {"role": "system", "content": "You are terse."},
                {"role": "user", "content": "hi"},
                {"role": "developer", "content": "Answer in German."},
            ],
        }
    )
    assert result["system"] == "You are terse.\nAnswer in German."
    assert result["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    assert result["max_tokens"] == 64


def test_a_request_without_a_cap_still_gets_one():
    # max_tokens is optional in OpenAI and required by the Messages API, so a
    # request that names none is a 400 unless one is supplied.
    result = to_messages({"model": "claude-opus-5", "messages": [{"role": "user", "content": "hi"}]})
    assert result["max_tokens"] == DEFAULT_OUTPUT_RESERVE_TOKENS


def test_max_completion_tokens_is_accepted_as_the_cap():
    # The spelling OpenAI's reasoning families take. Reading only max_tokens
    # would make a migrated client look like one that named no cap at all.
    result = to_messages({"model": "claude-opus-5", "max_completion_tokens": 32, "messages": []})
    assert result["max_tokens"] == 32


def test_openai_only_parameters_are_ignored_rather_than_forwarded():
    # Every one of these is an unknown field to the Messages API. The client
    # considers its request valid, so dropping them beats a 400.
    result = to_messages(
        {
            "model": "claude-opus-5",
            "max_tokens": 8,
            "messages": [],
            "n": 3,
            "seed": 42,
            "response_format": {"type": "json_object"},
            "frequency_penalty": 0.5,
            "presence_penalty": 0.5,
            "logprobs": True,
            "logit_bias": {"1": 1},
            "user": "u-1",
            "stream_options": {"include_usage": True},
        }
    )
    assert set(result) == {"model", "messages", "max_tokens"}


def test_temperature_is_clamped_to_the_anthropic_range():
    # OpenAI allows up to 2.0 and Anthropic caps at 1.0, where anything higher
    # is a 400 rather than a saturated value.
    assert to_messages({"model": "m", "messages": [], "temperature": 1.7})["temperature"] == 1.0
    assert to_messages({"model": "m", "messages": [], "temperature": 0.2})["temperature"] == 0.2


def test_stop_becomes_stop_sequences_in_both_spellings():
    assert to_messages({"model": "m", "messages": [], "stop": "END"})["stop_sequences"] == ["END"]
    assert to_messages({"model": "m", "messages": [], "stop": ["A", "B"]})["stop_sequences"] == ["A", "B"]


def test_tools_become_input_schema_definitions():
    result = to_messages(
        {
            "model": "m",
            "messages": [],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Look up the weather",
                        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                        "strict": True,
                    },
                },
                # A built-in tool type has no Anthropic counterpart; forwarding
                # it as an unknown shape would fail the whole request.
                {"type": "web_search"},
            ],
        }
    )
    assert result["tools"] == [
        {
            "name": "get_weather",
            "description": "Look up the weather",
            "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
        }
    ]


def test_a_function_without_parameters_still_declares_a_schema():
    # input_schema is required; a function that takes nothing becomes one that
    # takes an empty object.
    result = to_messages({"model": "m", "messages": [], "tools": [{"type": "function", "function": {"name": "now"}}]})
    assert result["tools"][0]["input_schema"] == {"type": "object", "properties": {}}


def test_tool_choice_spellings_map_across():
    def choice(value, parallel=None):
        payload = {"model": "m", "messages": [], "tools": [{"type": "function", "function": {"name": "t"}}]}
        payload["tool_choice"] = value
        if parallel is not None:
            payload["parallel_tool_calls"] = parallel
        return to_messages(payload).get("tool_choice")

    assert choice("auto") == {"type": "auto"}
    assert choice("none") == {"type": "none"}
    assert choice("required") == {"type": "any"}
    assert choice({"type": "function", "function": {"name": "t"}}) == {"type": "tool", "name": "t"}
    # Anthropic carries the parallel switch on tool_choice, so it folds in —
    # and needs a tool_choice to sit on when the client sent none.
    assert choice("auto", parallel=False) == {"type": "auto", "disable_parallel_tool_use": True}


def test_parallel_tool_calls_false_without_a_tool_choice():
    result = to_messages(
        {
            "model": "m",
            "messages": [],
            "parallel_tool_calls": False,
            "tools": [{"type": "function", "function": {"name": "t"}}],
        }
    )
    assert result["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}


def test_a_tool_round_trip_becomes_tool_use_and_tool_result():
    result = to_messages(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [
                {"role": "user", "content": "weather?"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"Munich"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "12°C"},
            ],
        }
    )
    assert result["messages"][1] == {
        "role": "assistant",
        # The empty string content produced no text block: an empty one is a
        # 400 on the Messages API.
        "content": [{"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {"city": "Munich"}}],
    }
    assert result["messages"][2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "12°C"}],
    }


def test_parallel_tool_results_are_merged_into_one_user_turn():
    # Anthropic wants every tool_result for the preceding assistant turn in a
    # single user turn, and rejects two user turns in a row.
    result = to_messages(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [
                {"role": "tool", "tool_call_id": "call_1", "content": "a"},
                {"role": "tool", "tool_call_id": "call_2", "content": "b"},
                {"role": "user", "content": "and now?"},
            ],
        }
    )
    assert len(result["messages"]) == 1
    assert [block.get("tool_use_id") or block["type"] for block in result["messages"][0]["content"]] == [
        "call_1",
        "call_2",
        "text",
    ]


def test_an_assistant_turn_with_nothing_in_it_is_dropped():
    # A client echoing back an empty assistant turn would otherwise produce
    # content: [], which the Messages API rejects.
    result = to_messages(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": ""}],
        }
    )
    assert [message["role"] for message in result["messages"]] == ["user"]


def test_images_map_onto_anthropic_sources():
    result = to_messages(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this?"},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
                        {"type": "image_url", "image_url": {"url": "https://example.test/cat.png"}},
                        # No Anthropic counterpart, and an unknown block type
                        # fails the whole request rather than the one part.
                        {"type": "input_audio", "input_audio": {"data": "x", "format": "wav"}},
                    ],
                }
            ],
        }
    )
    assert result["messages"][0]["content"] == [
        {"type": "text", "text": "what is this?"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"}},
        {"type": "image", "source": {"type": "url", "url": "https://example.test/cat.png"}},
    ]


def test_the_deprecated_function_call_spelling_survives():
    # Clients still sending it would otherwise lose the call, and the
    # conversation stops making sense at the result that answers it.
    result = to_messages(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [{"role": "assistant", "function_call": {"name": "now", "arguments": "{}"}}],
        }
    )
    block = result["messages"][0]["content"][0]
    assert block["type"] == "tool_use" and block["name"] == "now"
    # Anthropic rejects an empty tool_use id, so one is synthesised.
    assert block["id"]


# ── response ────────────────────────────────────────────────────────────────


def test_a_message_becomes_a_chat_completion():
    result = from_message(
        {
            "id": "msg_abc",
            "model": "claude-opus-5",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 31, "output_tokens": 27},
        }
    )
    assert result["object"] == "chat.completion"
    assert result["id"] == "chatcmpl-abc"
    assert result["choices"][0]["message"] == {"role": "assistant", "content": "Hello!", "refusal": None}
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"]["prompt_tokens"] == 31
    assert result["usage"]["completion_tokens"] == 27
    assert result["usage"]["total_tokens"] == 58


def test_tool_use_blocks_become_tool_calls():
    result = from_message(
        {
            "id": "msg_1",
            "model": "claude-opus-5",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Munich"}}],
            "stop_reason": "tool_use",
        }
    )
    message = result["choices"][0]["message"]
    assert message["tool_calls"] == [
        {"id": "toolu_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Munich"}'}}
    ]
    # Null rather than "", which is what OpenAI sends for a turn that was only
    # tool calls — clients branch on it.
    assert message["content"] is None
    assert result["choices"][0]["finish_reason"] == "tool_calls"


def test_thinking_blocks_are_dropped():
    # Anthropic-only, and a chat/completions client has nowhere to show them.
    result = from_message(
        {
            "content": [
                {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                {"type": "text", "text": "42"},
            ],
            "stop_reason": "end_turn",
        }
    )
    assert result["choices"][0]["message"]["content"] == "42"


def test_stop_reasons_map_onto_finish_reasons():
    def finish(reason):
        return from_message({"content": [{"type": "text", "text": "x"}], "stop_reason": reason})["choices"][0][
            "finish_reason"
        ]

    assert finish("end_turn") == "stop"
    assert finish("stop_sequence") == "stop"
    assert finish("max_tokens") == "length"
    assert finish("tool_use") == "tool_calls"
    assert finish("refusal") == "content_filter"
    # An unknown reason still ended the turn; inventing a condition the client
    # branches on would be worse than saying so plainly.
    assert finish("something_new") == "stop"


def test_cached_prompt_tokens_are_added_into_the_prompt_total():
    # Anthropic states cached tokens alongside input_tokens; OpenAI's
    # prompt_tokens is the whole prompt with cached_tokens as a subset of it.
    result = from_message(
        {
            "content": [],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 90,
                "cache_creation_input_tokens": 0,
            },
        }
    )
    assert result["usage"]["prompt_tokens"] == 100
    assert result["usage"]["prompt_tokens_details"] == {"cached_tokens": 90}
    assert result["usage"]["total_tokens"] == 105


def test_the_priced_cost_logos_adds_survives_the_translation():
    # Logos settles the cost onto the upstream usage object before this runs.
    # Dropping it makes a cloud model's cost disappear for clients on this path.
    result = from_message(
        {"content": [], "usage": {"input_tokens": 1, "output_tokens": 1, "cost": 0.00083, "cost_currency": "USD"}}
    )
    assert result["usage"]["cost"] == 0.00083
    assert result["usage"]["cost_currency"] == "USD"


# ── streaming ───────────────────────────────────────────────────────────────


def _feed(translator, *events):
    out = []
    for name, data in events:
        out.extend(translator.feed(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()))
    return out


def test_a_text_stream_is_rewritten_frame_by_frame():
    translator = MessagesStreamTranslator("claude-opus-5")
    chunks = _feed(
        translator,
        (
            "message_start",
            {
                "type": "message_start",
                "message": {"id": "msg_s", "model": "claude-opus-5", "usage": {"input_tokens": 7}},
            },
        ),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "He"}},
        ),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "llo"}},
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
        ),
        ("message_stop", {"type": "message_stop"}),
    )
    frames = _frames(chunks)

    assert frames[0]["object"] == "chat.completion.chunk"
    assert frames[0]["id"] == "chatcmpl-s"
    # The opening frame announces the role, the way chat/completions does.
    assert _deltas(frames)[0] == {"role": "assistant", "content": ""}
    assert "".join(delta.get("content", "") for delta in _deltas(frames)) == "Hello"
    assert frames[-3]["choices"][0]["finish_reason"] == "stop"
    # Usage arrives in its own frame with no choices, as chat/completions
    # reports it, and merges what message_start and message_delta each carried.
    assert frames[-2]["choices"] == []
    assert frames[-2]["usage"] == {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}
    assert frames[-1] == "[DONE]"


def test_tool_calls_are_renumbered_into_the_openai_index_space():
    # Anthropic numbers every content block; OpenAI numbers tool calls among
    # themselves, so a call in block 1 is tool_calls[0].
    translator = MessagesStreamTranslator("claude-opus-5")
    chunks = _feed(
        translator,
        ("message_start", {"type": "message_start", "message": {"id": "msg_t", "model": "claude-opus-5"}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "id": "toolu_1", "name": "get_weather"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"city":'},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '"Munich"}'},
            },
        ),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}}),
        ("message_stop", {"type": "message_stop"}),
    )
    frames = _frames(chunks)
    calls = [delta["tool_calls"][0] for delta in _deltas(frames) if "tool_calls" in delta]

    assert calls[0] == {
        "index": 0,
        "id": "toolu_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": ""},
    }
    assert "".join(call["function"]["arguments"] for call in calls) == '{"city":"Munich"}'
    assert all(call["index"] == 0 for call in calls)
    assert frames[-3]["choices"][0]["finish_reason"] == "tool_calls"


def test_thinking_deltas_are_dropped_from_the_stream():
    translator = MessagesStreamTranslator("claude-opus-5")
    chunks = _feed(
        translator,
        ("message_start", {"type": "message_start", "message": {"id": "msg_x", "model": "m"}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}}),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}},
        ),
    )
    assert all("content" not in delta or delta["content"] == "" for delta in _deltas(_frames(chunks)))


def test_an_upstream_error_event_becomes_an_openai_error_frame():
    translator = MessagesStreamTranslator("claude-opus-5")
    chunks = _feed(
        translator,
        ("message_start", {"type": "message_start", "message": {"id": "msg_e", "model": "m"}}),
        ("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    )
    frames = _frames(chunks)

    assert frames[-2] == {"error": {"message": "Overloaded", "type": "overloaded_error"}}
    assert frames[-1] == "[DONE]"
    # A terminal choice would read as a turn that completed normally.
    assert not any(frame != "[DONE]" and frame.get("choices") for frame in frames[-2:])


def test_finish_is_idempotent_after_message_stop():
    # main.py closes the stream again when the byte stream simply runs out,
    # and a second [DONE] would be a protocol error.
    translator = MessagesStreamTranslator("m")
    _feed(translator, ("message_stop", {"type": "message_stop"}))
    assert translator.finish() == []


def test_a_stream_that_never_terminated_is_still_closed():
    translator = MessagesStreamTranslator("m")
    _feed(
        translator,
        ("message_start", {"type": "message_start", "message": {"id": "msg_z", "model": "m"}}),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
        ),
    )
    frames = _frames(translator.finish())
    assert frames[0]["choices"][0]["finish_reason"] == "stop"
    assert frames[-1] == "[DONE]"
