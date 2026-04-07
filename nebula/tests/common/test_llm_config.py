import yaml

from nebula.common import config as llm_config


def _write_llm_config(tmp_path, entries):
    config_path = tmp_path / "llm_config.yml"
    config_path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return config_path


def test_load_llm_config_uses_env_path(monkeypatch, tmp_path):
    """Ensure load_llm_config reads from the configured file path."""
    config_entries = [
        {
            "model": "gpt-test",
            "type": "azure_chat",
            "endpoint": "https://example.azure.com",
            "azure_deployment": "gpt-test",
            "api_key": "abc",  # pragma: allowlist secret
            "api_version": "2024-01-01",
        }
    ]
    config_path = _write_llm_config(tmp_path, config_entries)
    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))

    entry = llm_config.load_llm_config(model="gpt-test")

    assert entry["azure_deployment"] == "gpt-test"
    assert entry["endpoint"] == "https://example.azure.com"


def test_get_openai_client_returns_azure_client(monkeypatch, tmp_path):
    """get_openai_client should instantiate AzureOpenAI when config requests it."""
    api_key = "azure-key"  # pragma: allowlist secret
    config_entries = [
        {
            "model": "gpt-azure",
            "type": "azure_chat",
            "endpoint": "https://azure.example.com",
            "azure_deployment": "gpt-azure-deploy",
            "api_key": api_key,
            "api_version": "2024-05-01",
        }
    ]
    config_path = _write_llm_config(tmp_path, config_entries)
    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))

    created_kwargs = {}

    class StubAzureClient:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

    monkeypatch.setattr(llm_config, "AzureOpenAI", StubAzureClient)

    client, deployment = llm_config.get_openai_client(model="gpt-azure")

    assert isinstance(client, StubAzureClient)
    assert deployment == "gpt-azure-deploy"
    assert created_kwargs["azure_endpoint"] == "https://azure.example.com"
    assert created_kwargs["azure_deployment"] == "gpt-azure-deploy"
    assert created_kwargs["api_version"] == "2024-05-01"


def test_get_openai_client_returns_openai_client(monkeypatch, tmp_path):
    """get_openai_client should instantiate OpenAI client for openai_chat configs."""
    api_key = "openai-key"  # pragma: allowlist secret
    config_entries = [
        {
            "model": "gpt-openai",
            "type": "openai_chat",
            "api_key": api_key,
        }
    ]
    config_path = _write_llm_config(tmp_path, config_entries)
    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))

    created_kwargs = {}

    class StubOpenAIClient:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

    monkeypatch.setattr(llm_config, "OpenAI", StubOpenAIClient)

    client, model = llm_config.get_openai_client(model="gpt-openai")

    assert isinstance(client, StubOpenAIClient)
    assert model == "gpt-openai"
    assert created_kwargs["api_key"] == api_key
