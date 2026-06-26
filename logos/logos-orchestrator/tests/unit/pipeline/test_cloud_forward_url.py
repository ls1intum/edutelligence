"""_cloud_forward_url: Azure deployment URLs must be forwarded as-is.

Regression test for the 404 caused by rebuilding cloud forward URLs from
base_url + inbound request path, which dropped the Azure deployment name and
api-version (e.g. ``.../openai/deployments/v1/chat/completions``).
"""

from logos.pipeline.context_resolver import ContextResolver

AZURE_BASE = "https://ase-se01.openai.azure.com/openai/deployments/"
AZURE_ENDPOINT = (
    "https://ase-se01.openai.azure.com/openai/deployments/"
    "gpt-41-mini/chat/completions?api-version=2025-01-01-preview"
)


def test_absolute_azure_endpoint_used_verbatim():
    # Even with an inbound request path, an absolute per-model endpoint wins:
    # the deployment name + api-version cannot be reconstructed from base_url.
    assert (
        ContextResolver._cloud_forward_url(AZURE_BASE, "/v1/chat/completions", AZURE_ENDPOINT)
        == AZURE_ENDPOINT
    )


def test_absolute_endpoint_used_when_no_request_path():
    assert ContextResolver._cloud_forward_url(AZURE_BASE, None, AZURE_ENDPOINT) == AZURE_ENDPOINT


def test_openai_shaped_upstream_forwards_like_for_like():
    # Relative/empty per-model endpoint => fall back to base_url + request path,
    # stripping a duplicated /v1 prefix.
    assert (
        ContextResolver._cloud_forward_url("https://api.openai.com/v1", "/v1/chat/completions", "")
        == "https://api.openai.com/v1/chat/completions"
    )


def test_relative_endpoint_merged_when_no_request_path():
    assert (
        ContextResolver._cloud_forward_url("https://api.openai.com/v1", None, "chat/completions")
        == "https://api.openai.com/v1/chat/completions"
    )
