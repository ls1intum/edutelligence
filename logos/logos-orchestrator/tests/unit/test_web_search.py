"""Search parsing, bounded HTTP requests, and gateway route behavior."""

import asyncio
from importlib import import_module
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import logos as main
from logos.dbutils.dbrequest import WebSearchRequest
from logos.routers import user_facing

search = import_module("logos.web_search")

RESULTS_HTML = """
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&amp;rut=unused">
    Python <b>Documentation</b> &amp; Help
  </a>
  <a class="result__snippet">Read <b>Python</b> documentation.</a>
</div>
<div class="result">
  <a class="result__a" href="https://docs.python.org/3/">Duplicate</a>
  <a class="result__snippet">Duplicate snippet</a>
</div>
<a class="result__a" href="javascript:alert(1)">Invalid</a>
<a class="result__snippet">Do not attach this to the previous result</a>
<a class="result__a" href="https://example.org/?a=1&amp;b=2">Second</a>
<a class="result__snippet">Another result</a>
"""


def mock_provider(monkeypatch, handler):
    original = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"] == 15
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(search.httpx, "AsyncClient", client)


async def test_search_decodes_results_and_contacts_only_search_host(monkeypatch):
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(200, text=RESULTS_HTML)

    mock_provider(monkeypatch, provider)
    results = await search.search_web("Python & asyncio", 10)
    assert results == [
        {
            "title": "Python Documentation & Help",
            "url": "https://docs.python.org/3/",
            "snippet": "Read Python documentation.",
        },
        {"title": "Second", "url": "https://example.org/?a=1&b=2", "snippet": "Another result"},
    ]
    assert len(requests) == 1
    assert str(requests[0].url).startswith(search.SEARCH_URL)
    assert requests[0].url.params["q"] == "Python & asyncio"
    assert "authorization" not in requests[0].headers


async def test_result_limit(monkeypatch):
    mock_provider(monkeypatch, lambda _: httpx.Response(200, text=RESULTS_HTML))
    assert len(await search.search_web("python", 1)) == 1


async def test_no_results_is_not_an_upstream_failure(monkeypatch):
    mock_provider(monkeypatch, lambda _: httpx.Response(200, text='<div class="no-results">No results</div>'))
    assert await search.search_web("nothing", 5) == []


@pytest.mark.parametrize(
    "status,page",
    [
        (429, "rate limited"),
        (302, "redirect"),
        (202, "challenge"),
        (200, '<form action="/anomaly.js">'),
        (200, "unknown"),
    ],
)
async def test_upstream_failures_are_explicit(monkeypatch, status, page):
    mock_provider(monkeypatch, lambda _: httpx.Response(status, text=page))
    with pytest.raises(search.SearchUnavailable):
        await search.search_web("python", 5)


async def test_network_timeout_is_reported(monkeypatch):
    def provider(request):
        raise httpx.ReadTimeout("timeout", request=request)

    mock_provider(monkeypatch, provider)
    with pytest.raises(search.SearchUnavailable, match="timed out"):
        await search.search_web("python", 5)


async def test_oversized_response_is_rejected(monkeypatch):
    mock_provider(monkeypatch, lambda _: httpx.Response(200, content=b"x" * 1_000_001))
    with pytest.raises(search.SearchUnavailable, match="oversized"):
        await search.search_web("python", 5)


async def test_waiting_for_a_search_slot_has_a_deadline(monkeypatch):
    slot = asyncio.Semaphore(1)
    await slot.acquire()
    timeout = asyncio.timeout
    monkeypatch.setattr(search, "_SEARCH_SLOTS", slot)
    monkeypatch.setattr(search.asyncio, "timeout", lambda _: timeout(0.01))
    with pytest.raises(search.SearchUnavailable, match="timed out"):
        await search.search_web("python", 5)
    slot.release()
    assert not slot.locked()


@pytest.mark.parametrize("href", ["javascript:alert(1)", "https://[broken", "https://example.org/" + "x" * 2048])
def test_invalid_result_urls_are_discarded(href):
    assert search._result_url(href) == ""


@pytest.mark.parametrize("query,limit", [(" ", 5), ("a" * 501, 5), ("valid", 0), ("valid", 11), ("valid", True)])
def test_invalid_request(query, limit):
    with pytest.raises(ValidationError):
        WebSearchRequest(query=query, max_results=limit)


async def test_route_is_before_catch_all_and_returns_search_results(monkeypatch):
    auth = Mock()
    lookup = AsyncMock(return_value=[{"title": "Python", "url": "https://python.org", "snippet": "Docs"}])
    monkeypatch.setattr(user_facing, "authenticate_api_key", auth)
    monkeypatch.setattr(user_facing, "search_web", lookup)
    monkeypatch.setattr(user_facing, "get_client_ip", lambda _: "127.0.0.1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/v1/web-search", json={"query": " Python "}, headers={"Authorization": "Bearer gateway-key"}
        )
    assert response.status_code == 200
    assert response.json() == {"query": "Python", "source": "DuckDuckGo", "results": lookup.return_value}
    lookup.assert_awaited_once_with("Python", 5)
    assert auth.call_args.args[0]["authorization"] == "Bearer gateway-key"
    assert auth.call_args.kwargs["client_ip"] == "127.0.0.1"


async def test_route_refuses_unauthenticated_searches(monkeypatch):
    lookup = AsyncMock()
    monkeypatch.setattr(user_facing, "search_web", lookup)
    monkeypatch.setattr(
        user_facing, "authenticate_api_key", Mock(side_effect=HTTPException(status_code=401, detail="Invalid key"))
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post("/v1/web-search", json={"query": "Python"})
    assert response.status_code == 401
    lookup.assert_not_awaited()


async def test_route_reports_search_failure(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    monkeypatch.setattr(user_facing, "search_web", AsyncMock(side_effect=search.SearchUnavailable("Try again later")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post("/v1/web-search", json={"query": "Python"})
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Try again later"
