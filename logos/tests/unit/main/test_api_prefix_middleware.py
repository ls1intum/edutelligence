"""Unit tests for APIPrefixStripperMiddleware in logos.main.

The middleware lets the UI namespace every internal call under `/api/*` so a
single Traefik route covers them all. These tests verify it strips the prefix
correctly for HTTP and WebSocket scopes, and leaves non-prefixed paths alone.
"""

import pytest

from logos.main import APIPrefixStripperMiddleware


class _Recorder:
    """Capture the scope passed through to the inner ASGI app."""

    def __init__(self):
        self.scope = None

    async def __call__(self, scope, receive, send):
        self.scope = scope


def _http_scope(path, raw_path=None, query_string=b""):
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": raw_path if raw_path is not None else path.encode("ascii"),
        "query_string": query_string,
        "headers": [],
    }


def _ws_scope(path, raw_path=None, query_string=b""):
    return {
        "type": "websocket",
        "path": path,
        "raw_path": raw_path if raw_path is not None else path.encode("ascii"),
        "query_string": query_string,
        "headers": [],
    }


@pytest.mark.asyncio
async def test_strips_api_prefix_from_http_path():
    inner = _Recorder()
    mw = APIPrefixStripperMiddleware(inner, prefix="/api")
    await mw(_http_scope("/api/me"), None, None)
    assert inner.scope["path"] == "/me"
    assert inner.scope["raw_path"] == b"/me"


@pytest.mark.asyncio
async def test_strips_api_prefix_from_websocket_path():
    inner = _Recorder()
    mw = APIPrefixStripperMiddleware(inner, prefix="/api")
    await mw(_ws_scope("/api/ws/stats/v2"), None, None)
    assert inner.scope["path"] == "/ws/stats/v2"
    assert inner.scope["raw_path"] == b"/ws/stats/v2"


@pytest.mark.asyncio
async def test_preserves_query_string_in_raw_path():
    inner = _Recorder()
    mw = APIPrefixStripperMiddleware(inner, prefix="/api")
    raw = b"/api/ws/stats?key=abc&x=1"
    await mw(
        _ws_scope("/api/ws/stats", raw_path=raw, query_string=b"key=abc&x=1"),
        None,
        None,
    )
    assert inner.scope["path"] == "/ws/stats"
    assert inner.scope["raw_path"] == b"/ws/stats?key=abc&x=1"


@pytest.mark.asyncio
async def test_bare_prefix_becomes_root():
    inner = _Recorder()
    mw = APIPrefixStripperMiddleware(inner, prefix="/api")
    await mw(_http_scope("/api"), None, None)
    assert inner.scope["path"] == "/"
    assert inner.scope["raw_path"] == b"/"


@pytest.mark.asyncio
async def test_unprefixed_path_passes_through_unchanged():
    inner = _Recorder()
    mw = APIPrefixStripperMiddleware(inner, prefix="/api")
    scope = _http_scope("/v1/chat/completions")
    await mw(scope, None, None)
    # Same scope object — middleware must not copy when no rewrite is needed
    assert inner.scope is scope
    assert inner.scope["path"] == "/v1/chat/completions"


@pytest.mark.asyncio
async def test_path_that_only_starts_with_api_word_is_not_stripped():
    """`/apidocs` must NOT be treated as `/docs` — only `/api` and `/api/...`."""
    inner = _Recorder()
    mw = APIPrefixStripperMiddleware(inner, prefix="/api")
    await mw(_http_scope("/apidocs"), None, None)
    assert inner.scope["path"] == "/apidocs"


@pytest.mark.asyncio
async def test_lifespan_scope_is_passed_through_untouched():
    inner = _Recorder()
    mw = APIPrefixStripperMiddleware(inner, prefix="/api")
    scope = {"type": "lifespan"}
    await mw(scope, None, None)
    assert inner.scope is scope
