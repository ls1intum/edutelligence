"""Cloud providers must fall back to the auth convention the UI advertises.

The provider form shows "Authorization" and "Bearer {}" as placeholders, so
operators routinely save an OpenAI-shaped cloud provider with both fields
empty. Before this fallback the header was dropped silently and the upstream
rejected every request as unauthenticated.
"""

from contextlib import contextmanager
from typing import Any, Dict, Optional

import pytest

from logos.pipeline import context_resolver as cr_module
from logos.pipeline.context_resolver import ContextResolver


@contextmanager
def _patched_db(monkeypatch, auth_info: Optional[Dict[str, Any]]):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get_auth_info_to_deployment(self, model_id, provider_id):  # noqa: ARG002
            return auth_info

    monkeypatch.setattr(cr_module, "DBManager", DummyDB)
    yield


def _auth_info(**overrides: Any) -> Dict[str, Any]:
    info = {
        "provider_type": "cloud",
        "provider_name": "Logos PROD",
        "model_name": "gpt-4.1-nano",
        "endpoint": "",
        "base_url": "https://logos.aet.cit.tum.de/v1",
        "api_key": "lg-secret",
        "auth_name": "",
        "auth_format": "",
    }
    info.update(overrides)
    return info


@pytest.mark.asyncio
async def test_empty_auth_fields_default_to_bearer(monkeypatch):
    with _patched_db(monkeypatch, _auth_info()):
        context = await ContextResolver().resolve_context(35, 4, "v1/chat/completions")

    assert context is not None
    assert context.auth_header == "Authorization"
    assert context.auth_value == "Bearer lg-secret"

    headers, _ = ContextResolver.prepare_headers_and_payload(context, {"model": "gpt-4.1-nano"})
    assert headers["Authorization"] == "Bearer lg-secret"


@pytest.mark.asyncio
async def test_explicit_header_name_keeps_bare_key(monkeypatch):
    # Azure stores auth_name="api-key" with auth_format="{}"; an explicit header
    # name must never acquire a Bearer prefix from the fallback.
    with _patched_db(monkeypatch, _auth_info(auth_name="api-key", auth_format="")):
        context = await ContextResolver().resolve_context(35, 4, "v1/chat/completions")

    assert context is not None
    assert context.auth_header == "api-key"
    assert context.auth_value == "lg-secret"


@pytest.mark.asyncio
async def test_explicit_auth_configuration_is_preserved(monkeypatch):
    with _patched_db(monkeypatch, _auth_info(auth_name="api-key", auth_format="{}")):
        context = await ContextResolver().resolve_context(35, 4, "v1/chat/completions")

    assert context is not None
    assert context.auth_header == "api-key"
    assert context.auth_value == "lg-secret"


@pytest.mark.asyncio
async def test_no_default_without_api_key(monkeypatch):
    # No key means nothing to send: keep the header absent rather than
    # forwarding an empty "Bearer ".
    with _patched_db(monkeypatch, _auth_info(api_key=None)):
        context = await ContextResolver().resolve_context(35, 4, "v1/chat/completions")

    assert context is not None
    assert context.auth_header == ""

    headers, _ = ContextResolver.prepare_headers_and_payload(context, {"model": "gpt-4.1-nano"})
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_credentials_are_not_sent_over_plain_http(monkeypatch):
    """A key must never go out in the clear.

    Same rule Logos already applies to these credentials on the benchmark
    path. Refused at resolve time, with a log line naming the provider, rather
    than leaking the key on every request.
    """
    with _patched_db(monkeypatch, _auth_info(base_url="http://upstream.example/v1")):
        assert await ContextResolver().resolve_context(35, 4, "v1/chat/completions") is None


@pytest.mark.asyncio
async def test_a_cleartext_per_model_endpoint_is_refused_too(monkeypatch):
    # base_url is https, but the request would go to the endpoint.
    info = _auth_info(
        base_url="https://upstream.example/v1",
        endpoint="http://upstream.example/v1/chat/completions",
    )
    with _patched_db(monkeypatch, info):
        assert await ContextResolver().resolve_context(35, 4, "v1/chat/completions") is None


@pytest.mark.asyncio
async def test_an_anthropic_provider_on_plain_http_is_refused(monkeypatch):
    info = _auth_info(cloud_provider_type="anthropic", base_url="http://api.anthropic.example/v1")
    with _patched_db(monkeypatch, info):
        assert await ContextResolver().resolve_context(35, 4, "v1/messages") is None


@pytest.mark.asyncio
async def test_loopback_http_keeps_working(monkeypatch):
    # Local development runs the upstream on localhost over plain HTTP.
    with _patched_db(monkeypatch, _auth_info(base_url="http://localhost:8000/v1")):
        context = await ContextResolver().resolve_context(35, 4, "v1/chat/completions")
    assert context is not None
    assert context.forward_url == "http://localhost:8000/v1/chat/completions"


@pytest.mark.asyncio
async def test_an_unauthenticated_cleartext_upstream_keeps_working(monkeypatch):
    # Nothing secret goes over the wire, so the transport rule does not apply.
    info = _auth_info(base_url="http://upstream.example/v1", api_key=None, auth_name="", auth_format="")
    with _patched_db(monkeypatch, info):
        context = await ContextResolver().resolve_context(35, 4, "v1/chat/completions")
    assert context is not None
    assert context.auth_header == ""
