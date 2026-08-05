import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from iris.qa.bootstrap import apply_local_llm_config, create_worker_configuration
from iris.qa.cost import ModelRate


def _card():
    return SimpleNamespace(
        candidates=(
            ModelRate("gpt-5.4-mini", Decimal("1"), Decimal("2")),
            ModelRate("gpt-5.5", Decimal("3"), Decimal("4")),
            ModelRate("gpt-5.6-sol", Decimal("5"), Decimal("30")),
            ModelRate("gpt-5.6-terra", Decimal("2.5"), Decimal("15")),
            ModelRate("gpt-5.6-luna", Decimal("1"), Decimal("6")),
            ModelRate("openai/gpt-oss-120b", Decimal("0"), Decimal("0")),
        ),
        judge=ModelRate("gpt-5.4", Decimal("5"), Decimal("6")),
    )


def test_bootstrap_uses_keyless_auth_without_serializing_secret(monkeypatch):
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_AZURE_AUTH_MODE", "azure_ad")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini-deployment")
    monkeypatch.setenv("IRIS_QA_GPT_55_DEPLOYMENT", "large-deployment")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge-deployment")
    config = create_worker_configuration(_card(), "gpt-5.5")
    try:
        models = yaml.safe_load(
            Path(config.environment["LLM_CONFIG_PATH"]).read_text(encoding="utf-8")
        )
        assert all(model["auth_mode"] == "azure_ad" for model in models)
        assert all("api_key" not in model for model in models)
        by_id = {model["id"]: model for model in models}
        assert by_id["qa-gpt-55"]["reasoning_effort"] == "medium"
        assert by_id["qa-aux-mini"]["reasoning_effort"] == "none"
        assert (
            by_id["qa-aux-mini"]["azure_deployment"]
            == by_id["qa-gpt-54-mini"]["azure_deployment"]
        )
        assert "qa-gpt-55" in Path(
            config.environment["APPLICATION_YML_PATH"]
        ).read_text(encoding="utf-8")
        assert "qa-aux-mini" in Path(
            config.environment["APPLICATION_YML_PATH"]
        ).read_text(encoding="utf-8")
    finally:
        config.close()


@pytest.mark.parametrize(
    ("model", "environment_name", "model_id"),
    (
        ("gpt-5.6-sol", "IRIS_QA_GPT_56_SOL_DEPLOYMENT", "qa-gpt-56-sol"),
        (
            "gpt-5.6-terra",
            "IRIS_QA_GPT_56_TERRA_DEPLOYMENT",
            "qa-gpt-56-terra",
        ),
        ("gpt-5.6-luna", "IRIS_QA_GPT_56_LUNA_DEPLOYMENT", "qa-gpt-56-luna"),
    ),
)
def test_gpt_56_candidates_leave_reasoning_at_provider_default(
    monkeypatch, model, environment_name, model_id
):
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge")
    monkeypatch.setenv(environment_name, model)

    config = create_worker_configuration(_card(), model)
    try:
        models = yaml.safe_load(
            Path(config.environment["LLM_CONFIG_PATH"]).read_text(encoding="utf-8")
        )
        candidate = next(item for item in models if item["id"] == model_id)
        assert "reasoning_effort" not in candidate
        assert candidate["model"] == model
        assert candidate["azure_deployment"] == model
        assert model_id in Path(config.environment["APPLICATION_YML_PATH"]).read_text(
            encoding="utf-8"
        )
    finally:
        config.close()


def test_logos_candidate_uses_openai_compatible_chat(monkeypatch):
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge")
    monkeypatch.setenv("IRIS_QA_LOGOS_BASE_URL", "https://logos.aet.cit.tum.de/v1")
    monkeypatch.setenv(
        "IRIS_QA_LOGOS_API_KEY",
        "logos-test-key",  # pragma: allowlist secret
    )
    monkeypatch.setenv("IRIS_QA_GPT_OSS_120B_MODEL", "openai/gpt-oss-120b")

    config = create_worker_configuration(_card(), "openai/gpt-oss-120b")
    try:
        models = yaml.safe_load(
            Path(config.environment["LLM_CONFIG_PATH"]).read_text(encoding="utf-8")
        )
        candidate = next(item for item in models if item["id"] == "qa-gpt-oss-120b")
        assert candidate["type"] == "openai_chat"
        assert candidate["model"] == "openai/gpt-oss-120b"
        assert candidate["base_url"] == "https://logos.aet.cit.tum.de/v1"
        assert candidate["api_key"] == "logos-test-key"  # pragma: allowlist secret
        assert candidate["use_responses_api"] is False
        assert "reasoning_effort" not in candidate
        assert "supports_reasoning_effort" not in candidate
    finally:
        config.close()


def test_bootstrap_rejects_shared_judge_deployment(monkeypatch):
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "same")
    monkeypatch.setenv("IRIS_QA_GPT_55_DEPLOYMENT", "large")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "same")
    try:
        create_worker_configuration(_card(), "gpt-5.5")
    except ValueError as error:
        assert "must be distinct" in str(error)
    else:
        raise AssertionError("shared judge deployment was accepted")


def test_mini_only_bootstrap_does_not_require_gpt_55_deployment(monkeypatch):
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge")
    monkeypatch.delenv("IRIS_QA_GPT_55_DEPLOYMENT", raising=False)

    config = create_worker_configuration(_card(), "gpt-5.4-mini")
    try:
        models = yaml.safe_load(
            Path(config.environment["LLM_CONFIG_PATH"]).read_text(encoding="utf-8")
        )
        assert {item["model"] for item in models} == {"gpt-5.4-mini", "gpt-5.4"}
    finally:
        config.close()


def test_bootstrap_rejects_endpoint_that_could_capture_bearer_token(monkeypatch):
    monkeypatch.setenv(
        "IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com.evil.example"
    )

    with pytest.raises(ValueError, match=r"HTTPS \*\.openai\.azure\.com"):
        create_worker_configuration(_card(), "gpt-5.5")


def test_bootstrap_rejects_an_explicitly_empty_api_version(monkeypatch):
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_GPT_55_DEPLOYMENT", "large")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge")
    monkeypatch.setenv("IRIS_QA_AZURE_API_VERSION", "")

    with pytest.raises(ValueError, match="API_VERSION must not be empty"):
        create_worker_configuration(_card(), "gpt-5.5")


def test_local_llm_config_populates_paid_run_environment(tmp_path, monkeypatch):
    managed = (
        "IRIS_QA_AZURE_ENDPOINT",
        "IRIS_QA_AZURE_AUTH_MODE",
        "IRIS_QA_AZURE_API_KEY",
        "IRIS_QA_AZURE_API_VERSION",
        "IRIS_QA_GPT_54_MINI_DEPLOYMENT",
        "IRIS_QA_GPT_55_DEPLOYMENT",
        "IRIS_QA_GPT_56_SOL_DEPLOYMENT",
        "IRIS_QA_GPT_56_TERRA_DEPLOYMENT",
        "IRIS_QA_GPT_56_LUNA_DEPLOYMENT",
        "IRIS_QA_JUDGE_DEPLOYMENT",
    )
    for name in managed:
        monkeypatch.setenv(name, "previous-value")
    path = tmp_path / "llm-config.yml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "existing-model",
                    "type": "azure_chat",
                    "model": "gpt-5-mini",
                    "endpoint": "https://qa.openai.azure.com/",
                    "api_key": "local-test-key",  # pragma: allowlist secret
                    "api_version": "2025-04-01-preview",
                    "azure_deployment": "existing-model",
                }
            ]
        ),
        encoding="utf-8",
    )

    metadata = apply_local_llm_config(path)

    assert metadata["endpoint"] == "https://qa.openai.azure.com"
    assert "credentialSource" not in metadata
    assert (
        os.environ["IRIS_QA_AZURE_API_KEY"]
        == "local-test-key"  # pragma: allowlist secret
    )
    assert os.environ["IRIS_QA_GPT_54_MINI_DEPLOYMENT"] == "gpt-5.4-mini"
    assert os.environ["IRIS_QA_GPT_55_DEPLOYMENT"] == "gpt-5.5"
    assert os.environ["IRIS_QA_GPT_56_SOL_DEPLOYMENT"] == "gpt-5.6-sol"
    assert os.environ["IRIS_QA_GPT_56_TERRA_DEPLOYMENT"] == "gpt-5.6-terra"
    assert os.environ["IRIS_QA_GPT_56_LUNA_DEPLOYMENT"] == "gpt-5.6-luna"
    assert os.environ["IRIS_QA_JUDGE_DEPLOYMENT"] == "gpt-5.4"


def test_local_llm_config_loads_logos_candidate(tmp_path):
    path = tmp_path / "llm-config.yml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "type": "azure_chat",
                    "model": "gpt-5.4",
                    "endpoint": "https://qa.openai.azure.com",
                    "api_key": "azure-test-key",  # pragma: allowlist secret
                    "azure_deployment": "judge",
                },
                {
                    "type": "openai_chat",
                    "model": "openai/gpt-oss-120b",
                    "base_url": "https://logos.aet.cit.tum.de/v1",
                    "api_key": "logos-test-key",  # pragma: allowlist secret
                },
            ]
        ),
        encoding="utf-8",
    )

    metadata = apply_local_llm_config(path)

    assert metadata["logosBaseUrl"] == "https://logos.aet.cit.tum.de/v1"
    assert os.environ["IRIS_QA_LOGOS_BASE_URL"] == metadata["logosBaseUrl"]
    assert (
        os.environ["IRIS_QA_LOGOS_API_KEY"]
        == "logos-test-key"  # pragma: allowlist secret
    )
    assert os.environ["IRIS_QA_GPT_OSS_120B_MODEL"] == "openai/gpt-oss-120b"


def test_local_llm_config_rejects_non_logos_gpt_oss_route(tmp_path):
    path = tmp_path / "llm-config.yml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "type": "azure_chat",
                    "endpoint": "https://qa.openai.azure.com",
                    "api_key": "azure-test-key",  # pragma: allowlist secret
                },
                {
                    "type": "openai_chat",
                    "model": "openai/gpt-oss-120b",
                    "base_url": "https://logos.aet.cit.tum.de.evil.example/v1",
                    "api_key": "logos-test-key",  # pragma: allowlist secret
                },
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Logos base URL must be"):
        apply_local_llm_config(path)


def test_local_llm_config_rejects_ambiguous_credentials(tmp_path):
    path = tmp_path / "llm-config.yml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "type": "azure_chat",
                    "endpoint": "https://qa.openai.azure.com",
                    "api_key": key,  # pragma: allowlist secret
                }
                for key in ("first-key", "second-key")
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="multiple credentials"):
        apply_local_llm_config(path)


def test_local_llm_config_uses_explicit_qa_deployment_names(tmp_path, monkeypatch):
    for name in (
        "IRIS_QA_AZURE_ENDPOINT",
        "IRIS_QA_AZURE_AUTH_MODE",
        "IRIS_QA_AZURE_API_KEY",
        "IRIS_QA_AZURE_API_VERSION",
        "IRIS_QA_GPT_54_MINI_DEPLOYMENT",
        "IRIS_QA_GPT_55_DEPLOYMENT",
        "IRIS_QA_GPT_56_SOL_DEPLOYMENT",
        "IRIS_QA_GPT_56_TERRA_DEPLOYMENT",
        "IRIS_QA_GPT_56_LUNA_DEPLOYMENT",
        "IRIS_QA_JUDGE_DEPLOYMENT",
    ):
        monkeypatch.setenv(name, "previous-value")
    path = tmp_path / "llm-config.yml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "type": "azure_chat",
                    "model": model,
                    "endpoint": "https://qa.openai.azure.com",
                    "api_key": "local-test-key",  # pragma: allowlist secret
                    "azure_deployment": deployment,
                }
                for model, deployment in (
                    ("gpt-5.4-mini", "mini-custom"),
                    ("gpt-5.5", "large-custom"),
                    ("gpt-5.6-sol", "sol-custom"),
                    ("gpt-5.6-terra", "terra-custom"),
                    ("gpt-5.6-luna", "luna-custom"),
                    ("gpt-5.4", "judge-custom"),
                )
            ]
        ),
        encoding="utf-8",
    )

    apply_local_llm_config(path)

    assert os.environ["IRIS_QA_GPT_54_MINI_DEPLOYMENT"] == "mini-custom"
    assert os.environ["IRIS_QA_GPT_55_DEPLOYMENT"] == "large-custom"
    assert os.environ["IRIS_QA_GPT_56_SOL_DEPLOYMENT"] == "sol-custom"
    assert os.environ["IRIS_QA_GPT_56_TERRA_DEPLOYMENT"] == "terra-custom"
    assert os.environ["IRIS_QA_GPT_56_LUNA_DEPLOYMENT"] == "luna-custom"
    assert os.environ["IRIS_QA_JUDGE_DEPLOYMENT"] == "judge-custom"
