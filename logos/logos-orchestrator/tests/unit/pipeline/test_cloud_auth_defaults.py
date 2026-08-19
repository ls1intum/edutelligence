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
