"""Anthropic's web search server tool, answered by Logos with DuckDuckGo."""

import base64
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

import logos as main
from logos.anthropic_compat import web_search as server
from logos.anthropic_compat.common import SSEDecoder
from logos.routers import user_facing
from logos.web_search import SearchUnavailable

TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 8}
FOUND = [
    {
        "title": "asyncio docs",
        "url": "https://docs.python.org/3/library/asyncio.html",
        "snippet": "asyncio is a library",
    },
    {"title": "A blog", "url": "https://blog.example.org/asyncio", "snippet": "my take"},
]


def search_request(**extra):
    return {
        "model": "Qwen/Qwen3.8-27B",
        "max_tokens": 1000,
        "system": "You are an assistant for performing a web search tool use",
        "messages": [{"role": "user", "content": "Perform a web search for the query: asyncio docs"}],
        "tools": [TOOL],
        **extra,
    }


def message(content, stop_reason="end_turn", input_tokens=100, output_tokens=10):
    return {
        "id": "msg_upstream",
        "type": "message",
        "role": "assistant",
        "model": "Qwen/Qwen3.8-27B",
        "content": content,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def search_call(query="asyncio docs", tool_id="toolu_1"):
    return {"type": "tool_use", "id": tool_id, "name": "web_search", "input": {"query": query}}


def model(*turns):
    sent = []

    async def call(payload):
        sent.append(json.loads(json.dumps(payload)))
        return turns[len(sent) - 1]

    return call, sent


@pytest.fixture
def ddg(monkeypatch):
    lookup = AsyncMock(return_value=FOUND)
    monkeypatch.setattr(server, "search_web", lookup)
    return lookup


def test_finds_only_the_web_search_server_tool():
    assert server.server_web_search_tool(search_request()) is TOOL
    assert server.server_web_search_tool({"tools": [{"name": "Bash", "input_schema": {}}]}) is None
    assert server.server_web_search_tool("not a payload") is None


async def test_search_then_answer(ddg):
    call, sent = model(
        (200, message([{"type": "text", "text": "Searching."}, search_call()], "tool_use")),
        (200, message([{"type": "text", "text": "See docs.python.org."}], input_tokens=300, output_tokens=20)),
    )
    status, result = await server.run(search_request(stream=True), TOOL, call)

    assert status == 200
    assert [b["type"] for b in result["content"]] == ["text", "server_tool_use", "web_search_tool_result", "text"]
    use, found = result["content"][1], result["content"][2]
    assert use == {
        "type": "server_tool_use",
        "id": "srvtoolu_1",
        "name": "web_search",
        "input": {"query": "asyncio docs"},
    }
    assert found["tool_use_id"] == "srvtoolu_1"
    assert [(r["title"], r["url"]) for r in found["content"]] == [(r["title"], r["url"]) for r in FOUND]
    assert base64.b64decode(found["content"][0]["encrypted_content"]).decode() == "asyncio is a library"
    assert result["stop_reason"] == "end_turn"
    assert result["usage"]["input_tokens"] == 400
    assert result["usage"]["output_tokens"] == 30
    assert result["usage"]["server_tool_use"] == {"web_search_requests": 1}
    ddg.assert_awaited_once_with("asyncio docs", 10)

    # The model sees an ordinary function tool and a non-streaming request...
    first, second = sent
    assert first["stream"] is False
    assert first["tools"] == [server._model_tool("web_search")]
    # ...and the results as the tool_result of its own call.
    assert second["messages"][-2] == {"role": "assistant", "content": first_turn_content(sent)}
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "toolu_1"
    assert json.loads(tool_result["content"]) == FOUND


def first_turn_content(sent):
    return [{"type": "text", "text": "Searching."}, search_call()]


async def test_answer_without_searching_passes_through(ddg):
    call, sent = model((200, message([{"type": "text", "text": "I know this."}])))
    status, result = await server.run(search_request(), TOOL, call)
    assert status == 200
    assert result["content"] == [{"type": "text", "text": "I know this."}]
    assert result["usage"]["server_tool_use"] == {"web_search_requests": 0}
    ddg.assert_not_awaited()


async def test_searches_stop_at_max_uses(ddg):
    tool = {**TOOL, "max_uses": 1}
    call, sent = model(
        (200, message([search_call("a", "toolu_a")], "tool_use")),
        (200, message([search_call("b", "toolu_b")], "tool_use")),
        (200, message([{"type": "text", "text": "Done."}])),
    )
    status, result = await server.run(search_request(tools=[tool]), tool, call)
    assert status == 200
    assert ddg.await_count == 1
    errors = [b["content"] for b in result["content"] if b["type"] == "web_search_tool_result"]
    assert errors[1] == {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}
    assert result["content"][-1] == {"type": "text", "text": "Done."}


async def test_a_model_that_never_stops_searching_is_cut_off(ddg):
    tool = {**TOOL, "max_uses": 1}
    call, sent = model(*[(200, message([search_call(tool_id=f"toolu_{i}")], "tool_use")) for i in range(10)])
    status, result = await server.run(search_request(tools=[tool]), tool, call)
    assert status == 200
    assert len(sent) == 3
    assert result["stop_reason"] == "end_turn"


async def test_client_tool_calls_go_back_to_the_client(ddg):
    bash = {"name": "Bash", "description": "run", "input_schema": {"type": "object"}}
    call, sent = model(
        (200, message([search_call(), {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {}}], "tool_use"))
    )
    status, result = await server.run(search_request(tools=[bash, TOOL]), TOOL, call)
    assert status == 200
    assert len(sent) == 1
    assert sent[0]["tools"][0] == bash
    assert [b["type"] for b in result["content"]] == ["server_tool_use", "web_search_tool_result", "tool_use"]
    assert result["stop_reason"] == "tool_use"


async def test_search_failure_is_a_tool_result_error(monkeypatch):
    monkeypatch.setattr(server, "search_web", AsyncMock(side_effect=SearchUnavailable("rate limited")))
    call, sent = model(
        (200, message([search_call()], "tool_use")),
        (200, message([{"type": "text", "text": "Search is down."}])),
    )
    status, result = await server.run(search_request(), TOOL, call)
    assert result["content"][1]["content"] == {"type": "web_search_tool_result_error", "error_code": "unavailable"}
    assert "rate limited" in sent[1]["messages"][-1]["content"][0]["content"]


async def test_model_errors_reach_the_client(ddg):
    error = {"type": "error", "error": {"type": "not_found_error", "message": "no such model"}}
    call, _ = model((404, error))
    assert await server.run(search_request(), TOOL, call) == (404, error)


async def test_domain_filters(ddg):
    tool = {**TOOL, "allowed_domains": ["python.org"]}
    call, _ = model((200, message([search_call()], "tool_use")), (200, message([{"type": "text", "text": "ok"}])))
    _, result = await server.run(search_request(tools=[tool]), tool, call)
    assert [r["url"] for r in result["content"][1]["content"]] == [FOUND[0]["url"]]
    ddg.assert_awaited_once_with("site:python.org asyncio docs", 10)

    tool = {**TOOL, "blocked_domains": ["example.org"]}
    call, _ = model((200, message([search_call()], "tool_use")), (200, message([{"type": "text", "text": "ok"}])))
    _, result = await server.run(search_request(tools=[tool]), tool, call)
    assert [r["url"] for r in result["content"][1]["content"]] == [FOUND[0]["url"]]


def test_history_with_server_blocks_becomes_tool_use_and_result():
    history = [
        {"role": "user", "content": "Find the asyncio docs and list the repo"},
        {
            "role": "assistant",
            "content": [
                {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "asyncio"}},
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "srvtoolu_1",
                    "content": [
                        {
                            "type": "web_search_result",
                            "title": "Docs",
                            "url": "https://d",
                            "encrypted_content": base64.b64encode(b"snip").decode(),
                        },
                        {
                            "type": "web_search_result",
                            "title": "Other",
                            "url": "https://o",
                            "encrypted_content": "opaque!",
                        },
                    ],
                },
                {"type": "text", "text": "Found it.", "citations": [{"type": "web_search_result_location"}]},
                {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "ls"}},
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_2", "content": "README"}]},
    ]
    converted = server.history_for_model(history)
    assert [m["role"] for m in converted] == ["user", "assistant", "user", "assistant", "user"]
    assert converted[1]["content"] == [
        {"type": "tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "asyncio"}}
    ]
    result = converted[2]["content"][0]
    assert result["tool_use_id"] == "srvtoolu_1"
    assert json.loads(result["content"]) == [
        {"title": "Docs", "url": "https://d", "snippet": "snip"},
        {"title": "Other", "url": "https://o", "snippet": ""},
    ]
    assert converted[3]["content"][0] == {"type": "text", "text": "Found it."}


def test_stream_events_rebuild_the_message():
    msg = {
        "id": "msg_1",
        "content": [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "q"}},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": []},
            {"type": "text", "text": "Answer"},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }
    events = [json.loads(data) for chunk in server.stream_rest(msg) for _, data in SSEDecoder().feed(chunk)]
    starts = [e["content_block"] for e in events if e["type"] == "content_block_start"]
    assert [b["type"] for b in starts] == ["server_tool_use", "web_search_tool_result", "text"]
    deltas = [e["delta"] for e in events if e["type"] == "content_block_delta"]
    assert json.loads(deltas[0]["partial_json"]) == {"query": "q"}
    assert deltas[1] == {"type": "text_delta", "text": "Answer"}
    assert [e["type"] for e in events[-2:]] == ["message_delta", "message_stop"]


# ── the route ───────────────────────────────────────────────────────────────


@pytest.fixture
def pipeline(monkeypatch, ddg):
    """The normal request pipeline, answering one model turn per call."""
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    turns = [
        JSONResponse(message([search_call()], "tool_use")),
        JSONResponse(message([{"type": "text", "text": "See docs.python.org."}])),
    ]
    seen = []

    async def handle(path, request):
        seen.append((path, await request.json(), request.headers.get("authorization")))
        return turns[len(seen) - 1]

    monkeypatch.setattr(user_facing, "handle_sync_request", handle)
    return seen


async def post(payload):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        return await client.post("/v1/messages?beta=true", json=payload, headers={"Authorization": "Bearer lg-key"})


async def test_route_answers_the_server_tool(pipeline):
    response = await post(search_request())
    assert response.status_code == 200
    body = response.json()
    assert [b["type"] for b in body["content"]] == ["server_tool_use", "web_search_tool_result", "text"]
    assert [path for path, _, _ in pipeline] == ["v1/messages", "v1/messages"]
    assert all(auth == "Bearer lg-key" for _, _, auth in pipeline)
    assert all(not any(t.get("type") == TOOL["type"] for t in sent["tools"]) for _, sent, _ in pipeline)


async def test_route_streams_the_server_tool(pipeline):
    response = await post(search_request(stream=True))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [(name, json.loads(data)) for name, data in SSEDecoder().feed(response.content)]
    assert events[0][0] == "message_start"
    assert events[-1][0] == "message_stop"
    starts = [e["content_block"]["type"] for name, e in events if name == "content_block_start"]
    assert starts == ["server_tool_use", "web_search_tool_result", "text"]


async def test_route_reports_a_failed_turn_in_the_stream(monkeypatch, ddg):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    monkeypatch.setattr(
        user_facing,
        "handle_sync_request",
        AsyncMock(side_effect=HTTPException(status_code=404, detail="no such model")),
    )
    response = await post(search_request(stream=True))
    events = [(name, json.loads(data)) for name, data in SSEDecoder().feed(response.content)]
    assert events[-1] == ("error", {"type": "error", "error": {"type": "not_found_error", "message": "no such model"}})


async def test_route_rejects_a_bad_key_before_streaming(monkeypatch):
    monkeypatch.setattr(
        user_facing, "authenticate_api_key", Mock(side_effect=HTTPException(status_code=401, detail="Invalid key"))
    )
    handle = AsyncMock()
    monkeypatch.setattr(user_facing, "handle_sync_request", handle)
    response = await post(search_request(stream=True))
    assert response.status_code == 401
    handle.assert_not_awaited()


async def test_other_messages_requests_are_untouched(monkeypatch):
    handle = AsyncMock(return_value=JSONResponse({"ok": True}))
    monkeypatch.setattr(user_facing, "handle_sync_request", handle)
    plain = search_request(tools=[{"name": "web_search_notes", "input_schema": {"type": "object"}}])
    response = await post(plain)
    assert response.json() == {"ok": True}
    assert handle.await_args.args[0] == "v1/messages"


async def test_route_reports_an_unexpected_failure_in_the_stream(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    monkeypatch.setattr(server, "run", AsyncMock(side_effect=RuntimeError("boom")))
    response = await post(search_request(stream=True))
    events = [(name, json.loads(data)) for name, data in SSEDecoder().feed(response.content)]
    assert events[0][0] == "message_start"
    assert events[-1] == ("error", {"type": "error", "error": {"type": "api_error", "message": "Web search failed."}})
