"""Pure-function tests for Azure deployment auto-sync planning."""

from logos.pipeline.ettft_estimator import ReadinessTier, estimate_ettft_azure
from logos.sdi.azure_deployment_sync import (
    _warn_if_not_an_azure_endpoint,
    azure_host_from_base_url,
    build_azure_endpoint,
    classify_azure_operation,
    plan_sync,
)
from logos.sdi.providers.azure_provider import AzureDataProvider, extract_azure_deployment_name

HOST = "https://ase-se01.openai.azure.com"


def test_host_from_base_url():
    assert azure_host_from_base_url(f"{HOST}/openai/deployments/") == HOST


def test_classify_chat_default():
    assert classify_azure_operation("gpt-4.1-mini").suffix == "chat/completions"


def test_classify_responses_for_gpt5_reasoning():
    assert classify_azure_operation("gpt-5.4").suffix == "responses"


def test_classify_gpt5_chat_stays_chat():
    assert classify_azure_operation("gpt-5-chat").suffix == "chat/completions"


def test_classify_embeddings_audio_image():
    assert classify_azure_operation("text-embedding-3-large").suffix == "embeddings"
    assert classify_azure_operation("whisper").suffix == "audio/transcriptions"
    assert classify_azure_operation("gpt-4o-mini-tts").suffix == "audio/speech"
    assert classify_azure_operation("dall-e-3").suffix == "images/generations"


def test_build_endpoint_chat_uses_deployment_id():
    op = classify_azure_operation("gpt-4.1-mini")
    url = build_azure_endpoint(HOST, "gpt-41-mini", op)
    assert url == f"{HOST}/openai/deployments/gpt-41-mini/chat/completions?api-version={op.api_version}"


def test_build_endpoint_responses_is_deployment_scoped():
    # Stored deployment-scoped (not the bare /openai/responses) so the id is
    # recoverable; ContextResolver collapses it to the real route at forward time.
    op = classify_azure_operation("gpt-5.4")
    assert build_azure_endpoint(HOST, "gpt-51", op) == (
        f"{HOST}/openai/deployments/gpt-51/responses?api-version={op.api_version}"
    )


def test_plan_prefers_matching_deployment_id():
    # gpt-4.1-mini is served by two deployments; the id matching the model wins.
    deployments = [
        {"id": "gpt-35-turbo", "model": "gpt-4.1-mini", "status": "succeeded"},
        {"id": "gpt-41-mini", "model": "gpt-4.1-mini", "status": "succeeded"},
    ]
    planned = plan_sync(HOST, deployments)
    assert len(planned) == 1
    assert planned[0]["model_name"] == "gpt-4.1-mini"
    assert "/deployments/gpt-41-mini/" in planned[0]["endpoint"]


def test_plan_captures_deployment_id_model_mismatch():
    # Deployment id 'gpt-4-turbo' actually serves model 'gpt-4o'.
    planned = plan_sync(HOST, [{"id": "gpt-4-turbo", "model": "gpt-4o", "status": "succeeded"}])
    assert planned[0]["model_name"] == "gpt-4o"
    assert "/deployments/gpt-4-turbo/" in planned[0]["endpoint"]


def test_plan_skips_unsucceeded():
    planned = plan_sync(HOST, [{"id": "x", "model": "gpt-x", "status": "creating"}])
    assert planned == []


def test_plan_keeps_responses_model_with_mismatched_deployment():
    # gpt-5.1 served by deployment 'gpt-4o' routes to /responses. The deployment
    # id is preserved in the URL so the body can be rewritten at forward time —
    # it is no longer dropped (regression: it used to be skipped as unroutable).
    planned = plan_sync(HOST, [{"id": "gpt-4o", "model": "gpt-5.1", "status": "succeeded"}])
    assert len(planned) == 1
    assert planned[0]["model_name"] == "gpt-5.1"
    assert "/deployments/gpt-4o/responses?" in planned[0]["endpoint"]


def test_plan_keeps_responses_model_with_matching_deployment():
    planned = plan_sync(HOST, [{"id": "gpt-5.4", "model": "gpt-5.4", "status": "succeeded"}])
    assert len(planned) == 1
    api_version = classify_azure_operation("gpt-5.4").api_version
    assert planned[0]["endpoint"] == f"{HOST}/openai/deployments/gpt-5.4/responses?api-version={api_version}"


def test_synced_responses_model_is_schedulable():
    # Regression for the registration path: a synced gpt-5 Responses model whose
    # deployment id differs from the served name must still register with the
    # Azure facade (deployment name extractable) and be scheduled as available,
    # not rejected with no capacity before it ever reaches the upstream.
    planned = plan_sync(HOST, [{"id": "gpt-4o", "model": "gpt-5.1", "status": "succeeded"}])
    endpoint = planned[0]["endpoint"]

    deployment_name = extract_azure_deployment_name(endpoint)
    assert deployment_name == "gpt-4o"  # registration would NOT filter this out

    provider = AzureDataProvider(name="azure", provider_id=1)
    provider.register_model(model_id=42, model_name="gpt-5.1", deployment_name=deployment_name)
    capacity = provider.get_capacity_info(deployment_name)
    assert estimate_ettft_azure(capacity).tier == ReadinessTier.WARM


# ── mislabelled provider diagnostics ────────────────────────────────────────
#
# A cloud provider typed 'azure' that is not one is discovered by nobody: this
# sync queries a data-plane route it does not serve, and the generic
# /v1/models sync skips everything typed 'azure' by design. The warning is the
# only thing connecting the empty catalogue to its cause, so it must survive
# every base_url an operator can type — it runs before any provider is synced
# and outside the per-provider guard, and start() awaits the first pass inline.


def test_an_azure_host_draws_no_warning(caplog):
    _warn_if_not_an_azure_endpoint({"id": 1, "name": "prod", "base_url": HOST})
    assert not caplog.records


def test_a_subdomain_of_azure_is_still_azure(caplog):
    # Azure OpenAI also answers on cognitiveservices.azure.com.
    _warn_if_not_an_azure_endpoint(
        {"id": 1, "name": "prod", "base_url": "https://x.cognitiveservices.azure.com/openai"}
    )
    assert not caplog.records


def test_a_foreign_host_is_named(caplog):
    _warn_if_not_an_azure_endpoint({"id": 25, "name": "Hetzner", "base_url": "https://inference.hetzner.com/api/v1"})
    assert "25" in caplog.text and "Hetzner" in caplog.text


def test_an_unparseable_base_url_warns_instead_of_raising(caplog):
    """urlsplit().hostname raises on a bracketed authority that is not IPv6."""
    _warn_if_not_an_azure_endpoint({"id": 3, "name": "typo", "base_url": "https://[not-an-ipv6"})
    assert "unparseable" in caplog.text


def test_a_missing_base_url_warns_instead_of_raising(caplog):
    _warn_if_not_an_azure_endpoint({"id": 4, "name": "blank", "base_url": None})
    assert caplog.records
