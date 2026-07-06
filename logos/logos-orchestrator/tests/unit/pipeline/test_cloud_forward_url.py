"""_cloud_forward_url: Azure deployment URLs must be forwarded as-is.

Regression test for the 404 caused by rebuilding cloud forward URLs from
base_url + inbound request path, which dropped the Azure deployment name and
api-version (e.g. ``.../openai/deployments/v1/chat/completions``).

Also covers ``_azure_responses_route`` / body rewriting: Azure Responses
deployments are stored deployment-scoped so the id survives, then collapsed to
the real ``/openai/responses`` route with the body ``model`` rewritten to the
deployment id at forward time.
"""

from logos.pipeline.context_resolver import ContextResolver, ExecutionContext

AZURE_BASE = "https://ase-se01.openai.azure.com/openai/deployments/"
AZURE_ENDPOINT = (
    "https://ase-se01.openai.azure.com/openai/deployments/"
    "gpt-41-mini/chat/completions?api-version=2025-01-01-preview"
)


def test_absolute_azure_endpoint_used_verbatim():
    # Even with an inbound request path, an absolute per-model endpoint wins:
    # the deployment name + api-version cannot be reconstructed from base_url.
    assert ContextResolver._cloud_forward_url(AZURE_BASE, "/v1/chat/completions", AZURE_ENDPOINT) == AZURE_ENDPOINT


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


def test_azure_responses_route_collapses_and_extracts_deployment():
    # Deployment-scoped Responses URL -> real /openai/responses route + the
    # deployment id the body "model" must be rewritten to.
    url = "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/responses?api-version=2025-04-01-preview"
    real_url, deployment = ContextResolver._azure_responses_route(url)
    assert real_url == "https://ase-se01.openai.azure.com/openai/responses?api-version=2025-04-01-preview"
    assert deployment == "gpt-4o"


def test_azure_responses_route_ignores_chat_completions():
    # Chat completions carry the deployment in the path; no rewrite needed.
    assert ContextResolver._azure_responses_route(AZURE_ENDPOINT) == (None, None)


def test_prepare_payload_rewrites_model_for_azure_responses():
    # The client addresses the served name (gpt-5.1); Azure /responses needs the
    # deployment id (gpt-4o) in the body to resolve the deployment.
    context = ExecutionContext(
        model_id=1,
        provider_id=1,
        provider_name="Azure SE01",
        provider_type="cloud",
        forward_url="https://ase-se01.openai.azure.com/openai/responses?api-version=2025-04-01-preview",
        auth_header="api-key",
        auth_value="secret",
        model_name="gpt-5.1",
        azure_responses_deployment="gpt-4o",
    )
    _, payload = ContextResolver.prepare_headers_and_payload(context, {"model": "gpt-5.1", "input": "hi"})
    assert payload["model"] == "gpt-4o"


def test_prepare_payload_leaves_model_untouched_without_responses_deployment():
    context = ExecutionContext(
        model_id=1,
        provider_id=1,
        provider_name="Azure SE01",
        provider_type="cloud",
        forward_url=AZURE_ENDPOINT,
        auth_header="api-key",
        auth_value="secret",
        model_name="gpt-4.1-mini",
    )
    _, payload = ContextResolver.prepare_headers_and_payload(context, {"model": "gpt-4.1-mini"})
    assert payload["model"] == "gpt-4.1-mini"
