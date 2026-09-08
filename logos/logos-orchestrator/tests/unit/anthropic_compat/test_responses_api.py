"""Anthropic Messages ⇄ the OpenAI Responses API.

The dialect a gpt-5.x Azure deployment is addressed with: the conversation is
a flat ``input`` list whose tool calls and results are top-level items, and the
event stream names every event.
"""

import json

from logos.anthropic_compat.responses_api import ResponsesStreamTranslator, from_response, to_responses


def _events(chunks):
    text = b"".join(chunks).decode()
    out = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        out.append((name, data))
    return out


def _sse(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


# ── request ─────────────────────────────────────────────────────────────────


def test_system_becomes_instructions_and_max_tokens_becomes_max_output_tokens():
    result = to_responses(
        {
            "model": "gpt-5.6-luna",
            "max_tokens": 512,
            "system": "Be brief.",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    assert result["instructions"] == "Be brief."
    assert result["max_output_tokens"] == 512
    assert result["input"] == [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}]


def test_sampling_parameters_are_not_forwarded():
    # This dialect is only reached for reasoning deployments, which reject
    # temperature and top_p — and Anthropic clients send one on every request.
    result = to_responses({"model": "m", "max_tokens": 8, "temperature": 1, "top_p": 0.9, "messages": []})
    assert "temperature" not in result and "top_p" not in result


def test_tool_call_and_result_become_top_level_items():
    result = to_responses(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "running"},
                        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "a.py"},
                        {"type": "text", "text": "thanks"},
                    ],
                },
            ],
        }
    )
    assert result["input"] == [
        # input_text, not output_text: an output item would also need an id
        # and a status, and a request message carries neither.
        {"type": "message", "role": "assistant", "content": [{"type": "input_text", "text": "running"}]},
        {"type": "function_call", "call_id": "toolu_1", "name": "Bash", "arguments": '{"command": "ls"}'},
        {"type": "function_call_output", "call_id": "toolu_1", "output": "a.py"},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "thanks"}]},
    ]


def test_tools_use_the_flat_responses_shape():
    result = to_responses(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [],
            "tools": [{"name": "Bash", "description": "run", "input_schema": {"type": "object"}}],
            "tool_choice": {"type": "any"},
        }
    )
    assert result["tools"] == [
        {"type": "function", "name": "Bash", "description": "run", "parameters": {"type": "object"}}
    ]
    assert result["tool_choice"] == "required"


def test_effort_becomes_a_reasoning_block():
    result = to_responses({"model": "m", "max_tokens": 8, "messages": [], "output_config": {"effort": "medium"}})
    assert result["reasoning"] == {"effort": "medium"}


# ── response ────────────────────────────────────────────────────────────────


def test_message_output_becomes_text_content():
    result = from_response(
        {
            "id": "resp_1",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "output": [
                # A reasoning item has no Anthropic counterpart a client could
                # echo back, so it is dropped rather than half-translated.
                {"type": "reasoning", "summary": []},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}]},
            ],
            "usage": {"input_tokens": 12, "output_tokens": 1, "input_tokens_details": {"cached_tokens": 4}},
        }
    )
    assert result["id"] == "msg_resp_1"
    assert result["content"] == [{"type": "text", "text": "OK"}]
    assert result["stop_reason"] == "end_turn"
    assert result["usage"]["input_tokens"] == 12
    assert result["usage"]["cache_read_input_tokens"] == 4


def test_function_call_output_reports_tool_use():
    result = from_response(
        {
            "id": "resp_2",
            "model": "m",
            "status": "completed",
            "output": [{"type": "function_call", "call_id": "fc_1", "name": "Bash", "arguments": '{"command":"ls"}'}],
        }
    )
    assert result["stop_reason"] == "tool_use"
    assert result["content"] == [{"type": "tool_use", "id": "fc_1", "name": "Bash", "input": {"command": "ls"}}]


def test_incomplete_response_reports_max_tokens():
    result = from_response(
        {
            "id": "r",
            "model": "m",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
        }
    )
    assert result["stop_reason"] == "max_tokens"


# ── streaming ───────────────────────────────────────────────────────────────


def test_text_stream_emits_the_anthropic_sequence():
    translator = ResponsesStreamTranslator("m")
    out = []
    out += translator.feed(_sse("response.created", {"response": {"id": "resp_9", "model": "m"}}))
    out += translator.feed(_sse("response.output_text.delta", {"output_index": 0, "delta": "He"}))
    out += translator.feed(_sse("response.output_text.delta", {"output_index": 0, "delta": "llo"}))
    out += translator.feed(
        _sse(
            "response.completed",
            {"response": {"status": "completed", "usage": {"input_tokens": 7, "output_tokens": 2}}},
        )
    )

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
    assert events[0][1]["message"]["id"] == "msg_resp_9"
    assert "".join(d["delta"]["text"] for n, d in events if n == "content_block_delta") == "Hello"
    assert events[-2][1]["usage"]["output_tokens"] == 2


def test_function_call_stream_becomes_a_tool_use_block():
    translator = ResponsesStreamTranslator("m")
    out = []
    out += translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    out += translator.feed(
        _sse(
            "response.output_item.added",
            {"output_index": 0, "item": {"type": "function_call", "call_id": "fc_1", "name": "Bash"}},
        )
    )
    out += translator.feed(_sse("response.function_call_arguments.delta", {"output_index": 0, "delta": '{"cmd":'}))
    out += translator.feed(_sse("response.function_call_arguments.delta", {"output_index": 0, "delta": '"ls"}'}))
    out += translator.feed(_sse("response.completed", {"response": {"status": "completed"}}))

    events = _events(out)
    start = next(d for n, d in events if n == "content_block_start")
    assert start["content_block"] == {"type": "tool_use", "id": "fc_1", "name": "Bash", "input": {}}
    partial = "".join(d["delta"]["partial_json"] for n, d in events if n == "content_block_delta")
    assert json.loads(partial) == {"cmd": "ls"}
    assert next(d for n, d in events if n == "message_delta")["delta"]["stop_reason"] == "tool_use"


def test_incomplete_stream_reports_max_tokens():
    translator = ResponsesStreamTranslator("m")
    translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    out = translator.feed(
        _sse(
            "response.incomplete",
            {"response": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}},
        )
    )
    assert next(d for n, d in _events(out) if n == "message_delta")["delta"]["stop_reason"] == "max_tokens"


def test_failed_response_becomes_an_error_event():
    translator = ResponsesStreamTranslator("m")
    translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    out = translator.feed(_sse("response.failed", {"response": {"error": {"message": "rate limited"}}}))
    events = _events(out)
    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["message"] == "rate limited"


def test_string_error_field_keeps_the_upstream_message():
    # The spec says `error` is an object, but upstreams do send a bare string;
    # dropping that shape would replace the real cause with the fallback.
    translator = ResponsesStreamTranslator("m")
    translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    out = translator.feed(_sse("error", {"error": "quota exhausted"}))
    assert _events(out)[-1][1]["error"]["message"] == "quota exhausted"


def test_error_without_a_usable_message_falls_back():
    translator = ResponsesStreamTranslator("m")
    translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    out = translator.feed(_sse("error", {"error": {}}))
    assert _events(out)[-1][1]["error"]["message"] == "upstream stream error"


def test_multibyte_character_split_across_chunks_survives():
    translator = ResponsesStreamTranslator("m")
    translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    frame = json.dumps({"output_index": 0, "delta": "Größe 🎉"}, ensure_ascii=False)
    raw = f"event: response.output_text.delta\ndata: {frame}\n\n".encode()
    split = raw.index("ö".encode()) + 1  # mid-character
    out = translator.feed(raw[:split]) + translator.feed(raw[split:])
    assert "".join(d["delta"]["text"] for n, d in _events(out) if n == "content_block_delta") == "Größe 🎉"


def test_assistant_history_uses_request_content_types():
    """Replayed assistant text must be a request message, not an output item.

    ``output_text`` belongs to an output item, which also carries an ``id`` and
    a ``status``; emitting it without them is not a valid input item, so the
    second turn of any conversation could be rejected outright.
    """
    result = to_responses(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "again"},
            ],
        }
    )
    kinds = {part["type"] for item in result["input"] for part in item["content"]}
    assert kinds == {"input_text"}
    assert all("id" not in item and "status" not in item for item in result["input"])


def test_interleaved_function_call_arguments_are_not_lost():
    """Fragments of a call that is no longer the open block must survive.

    Only one Anthropic content block is open at a time, so relaying fragments
    as they arrive drops everything belonging to any other call — leaving
    truncated JSON that the client would hand to the tool.
    """
    translator = ResponsesStreamTranslator("m")
    out = []
    out += translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    for index, call_id, name in ((0, "fc_0", "Bash"), (1, "fc_1", "Read")):
        out += translator.feed(
            _sse(
                "response.output_item.added",
                {"output_index": index, "item": {"type": "function_call", "call_id": call_id, "name": name}},
            )
        )
    out += translator.feed(_sse("response.function_call_arguments.delta", {"output_index": 0, "delta": '{"cmd":'}))
    out += translator.feed(_sse("response.function_call_arguments.delta", {"output_index": 1, "delta": '{"path":"a"}'}))
    out += translator.feed(_sse("response.function_call_arguments.delta", {"output_index": 0, "delta": '"ls"}'}))
    out += translator.feed(_sse("response.completed", {"response": {"status": "completed"}}))

    assert _tool_inputs(_events(out)) == {"fc_0": {"cmd": "ls"}, "fc_1": {"path": "a"}}


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


def test_a_truncated_function_call_reports_max_tokens_not_tool_use():
    """Running out of max_output_tokens mid-call is a length stop.

    Reporting tool_use there hands the client arguments that are cut off
    mid-JSON and tells it to execute them.
    """
    result = from_response(
        {
            "id": "r",
            "model": "m",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "function_call", "call_id": "fc_1", "name": "Bash", "arguments": '{"command":"rm -'}],
        }
    )
    assert result["stop_reason"] == "max_tokens"


def test_an_unnamed_error_frame_is_not_mistaken_for_a_completed_turn():
    """The executor appends a bare data: {"error": ...} frame, then [DONE].

    It carries no event name, so falling through to the terminal events would
    report end_turn and make a truncated answer look successful.
    """
    translator = ResponsesStreamTranslator("m")
    translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    translator.feed(_sse("response.output_text.delta", {"output_index": 0, "delta": "partial"}))

    out = translator.feed(b'data: {"error": {"message": "connection reset", "type": "api_error"}}\n\n')
    out += translator.feed(b"data: [DONE]\n\n")

    events = _events(out)
    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["message"] == "connection reset"
    assert "message_stop" not in [name for name, _ in events]


def test_no_content_is_emitted_after_a_mid_stream_error():
    translator = ResponsesStreamTranslator("m")
    translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    translator.feed(
        _sse(
            "response.output_item.added",
            {"output_index": 0, "item": {"type": "function_call", "call_id": "fc_1", "name": "Bash"}},
        )
    )
    events = _events(translator.error("connection reset"))
    assert [name for name, _ in events] == ["error"]
    assert translator.finish() == []


def test_a_safety_refusal_reaches_the_client():
    """A refusal is a content part of its own, not an output_text."""
    result = from_response(
        {
            "id": "r",
            "model": "m",
            "status": "completed",
            "output": [
                {"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "I can't."}]}
            ],
        }
    )
    assert result["content"] == [{"type": "text", "text": "I can't."}]


def test_a_streamed_refusal_reaches_the_client():
    translator = ResponsesStreamTranslator("m")
    translator.feed(_sse("response.created", {"response": {"id": "r", "model": "m"}}))
    out = translator.feed(_sse("response.refusal.delta", {"output_index": 0, "delta": "I can't."}))
    out += translator.feed(_sse("response.completed", {"response": {"status": "completed"}}))
    answer = "".join(d["delta"]["text"] for n, d in _events(out) if n == "content_block_delta")
    assert answer == "I can't."


def test_disable_parallel_tool_use_is_carried_over():
    """The Responses API defaults parallel_tool_calls to true as well."""
    request = {
        "model": "m",
        "max_tokens": 8,
        "messages": [],
        "tools": [{"name": "Bash", "description": "run", "input_schema": {"type": "object"}}],
        "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
    }
    assert to_responses(request)["parallel_tool_calls"] is False

    for choice in ({"type": "any"}, {"type": "any", "disable_parallel_tool_use": False}):
        assert "parallel_tool_calls" not in to_responses({**request, "tool_choice": choice})


def test_parallel_tool_calls_is_not_sent_without_tools():
    result = to_responses(
        {
            "model": "m",
            "max_tokens": 8,
            "messages": [],
            "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
        }
    )
    assert "parallel_tool_calls" not in result
