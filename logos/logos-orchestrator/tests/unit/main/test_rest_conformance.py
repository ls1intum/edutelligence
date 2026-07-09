"""REST conformance of the user-facing surface.

The proxy catch-alls (/v1, /v2, /openai, /jobs/*) are POST-only — every
proxied upstream operation is a POST. Other methods must yield a proper
405 (with Allow header, in the OpenAI error shape) instead of the misleading
"400 Invalid JSON body" the body parser used to raise on body-less GETs.
"""

from fastapi import HTTPException
from fastapi.testclient import TestClient

import logos as main
from logos.main import _http_exception_handler

client = TestClient(main.app, raise_server_exceptions=False)


def test_get_on_proxy_catch_all_returns_405_with_allow():
    resp = client.get("/v1/chat/completions")
    assert resp.status_code == 405
    assert "POST" in resp.headers.get("allow", "")
    body = resp.json()
    assert body["error"]["type"]  # OpenAI error shape


def test_put_and_delete_on_proxy_catch_alls_return_405():
    assert client.put("/openai/chat/completions", json={}).status_code == 405
    assert client.delete("/v2/rerank").status_code == 405
    assert client.get("/jobs/v1/chat/completions").status_code == 405


def test_models_listing_still_get():
    # GET /v1/models must not be swallowed by the POST-only catch-all
    # (401 without credentials — not 405).
    resp = client.get("/v1/models")
    assert resp.status_code == 401


def test_openai_models_alias_registered():
    # The /openai prefix mirrors /v1; model listing/retrieval must exist there
    # too (previously the catch-all answered these GETs with 400).
    routes = {(route.path, method) for route in main.app.routes for method in getattr(route, "methods", None) or ()}
    assert ("/openai/models", "GET") in routes
    assert ("/openai/models/{model_id:path}", "GET") in routes


async def test_http_exception_handler_preserves_headers():
    # Protocol-mandated headers (Allow on 405, Retry-After on 429) must
    # survive the conversion to the OpenAI error shape.
    exc = HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": "60"})
    resp = await _http_exception_handler(None, exc)
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "60"
