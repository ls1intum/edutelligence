"""Embedding calls go through one retry layer: the SDK clients do not retry."""

# pylint: skip-file

import httpx
import pytest
from openai import APITimeoutError, InternalServerError

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.external.openai_embeddings import (  # noqa: E402
    AzureOpenAIEmbeddingModel,
    DirectOpenAIEmbeddingModel,
)
from iris.llm.retry import MAX_ATTEMPTS, MAX_TIMEOUT_RETRIES, RetryState  # noqa: E402


@pytest.fixture
def transport(monkeypatch):
    """Count the HTTP requests that actually leave the client."""
    calls = {"count": 0, "mode": "error"}

    def send(self, request, **_kwargs):
        calls["count"] += 1
        if calls["mode"] == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(500, json={"error": {"message": "down"}}, request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(RetryState, "wait", lambda self, error, attempt: None)
    return calls


def _direct():
    return DirectOpenAIEmbeddingModel(
        id="emb",
        name="emb",
        description="",
        model="text-embedding-3-small",
        type="openai_embedding",
        api_key="key",  # pragma: allowlist secret
        base_url="http://embeddings.invalid/v1",
    )


def _azure():
    return AzureOpenAIEmbeddingModel(
        id="emb",
        name="emb",
        description="",
        model="text-embedding-3-small",
        type="azure_embedding",
        api_key="key",  # pragma: allowlist secret
        endpoint="http://azure.invalid",
        azure_deployment="emb",
        api_version="2024-10-21",
    )


@pytest.mark.parametrize("factory", [_direct, _azure])
def test_a_server_error_is_sent_at_most_max_attempts_times(transport, factory):
    with pytest.raises(InternalServerError):
        factory().embed("heap")

    assert transport["count"] == MAX_ATTEMPTS


@pytest.mark.parametrize("factory", [_direct, _azure])
def test_a_timeout_is_retried_only_once(transport, factory):
    transport["mode"] = "timeout"

    with pytest.raises(APITimeoutError):
        factory().embed("heap")

    assert transport["count"] == 1 + MAX_TIMEOUT_RETRIES


def test_semantic_chunking_embeddings_use_the_same_retries(transport):
    with pytest.raises(InternalServerError):
        _direct().split_text_semantically("One. Two. Three.")

    assert transport["count"] == MAX_ATTEMPTS
