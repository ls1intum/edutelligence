"""Pure-function tests for Azure deployment auto-sync planning."""

from logos.sdi.azure_deployment_sync import (
    azure_host_from_base_url,
    build_azure_endpoint,
    classify_azure_operation,
    plan_sync,
)

HOST = "https://ase-se01.openai.azure.com"


def test_host_from_base_url():
    assert azure_host_from_base_url(f"{HOST}/openai/deployments/") == HOST


def test_classify_chat_default():
    op = classify_azure_operation("gpt-4.1-mini")
    assert op.suffix == "chat/completions"
    assert op.uses_deployment_path


def test_classify_responses_for_gpt5_reasoning():
    op = classify_azure_operation("gpt-5.4")
    assert op.suffix == ""
    assert not op.uses_deployment_path


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


def test_build_endpoint_responses_has_no_deployment():
    op = classify_azure_operation("gpt-5.4")
    assert build_azure_endpoint(HOST, "gpt-5.4", op) == f"{HOST}/openai/responses?api-version={op.api_version}"


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


def test_plan_skips_responses_model_with_mismatched_deployment():
    # gpt-5.1 served by deployment 'gpt-4o' routes to /responses, which keys off
    # the body model name — unroutable, so it must be dropped.
    planned = plan_sync(HOST, [{"id": "gpt-4o", "model": "gpt-5.1", "status": "succeeded"}])
    assert planned == []


def test_plan_keeps_responses_model_with_matching_deployment():
    planned = plan_sync(HOST, [{"id": "gpt-5.4", "model": "gpt-5.4", "status": "succeeded"}])
    assert len(planned) == 1
    assert planned[0]["endpoint"].endswith("/openai/responses?api-version=" + classify_azure_operation("gpt-5.4").api_version)
