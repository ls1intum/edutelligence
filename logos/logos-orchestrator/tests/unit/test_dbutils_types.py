from logos.dbutils.types import infer_cloud_provider_type


def test_infer_cloud_provider_type_from_azure_hostname():
    assert (
        infer_cloud_provider_type(
            "cloud",
            base_url="https://sample.openai.azure.com/openai/deployments/gpt-4o",
        )
        == "azure"
    )


def test_infer_cloud_provider_type_rejects_azure_text_outside_hostname():
    assert (
        infer_cloud_provider_type(
            "cloud",
            base_url="https://example.com/proxy/openai.azure.com/deployments/gpt-4o",
        )
        is None
    )
    assert infer_cloud_provider_type("cloud", base_url="https://sample.openai.azure.com.evil.test") is None


def test_infer_cloud_provider_type_honors_explicit_azure_type():
    assert infer_cloud_provider_type("azure", base_url="https://example.com") == "azure"


def test_anthropic_defaults_to_the_x_api_key_header():
    from logos.dbutils.types import cloud_auth_header

    # The provider form's placeholders are Authorization/Bearer, which
    # Anthropic ignores — a provider saved with them would never authenticate.
    assert cloud_auth_header("", "", "sk-ant", "anthropic") == ("x-api-key", "sk-ant")
    assert cloud_auth_header("", "", "sk-oai", "openai") == ("Authorization", "Bearer sk-oai")
    # An explicit choice is never overridden.
    assert cloud_auth_header("Authorization", "Bearer {}", "sk-ant", "anthropic") == (
        "Authorization",
        "Bearer sk-ant",
    )


def test_anthropic_requires_its_version_header():
    from logos.dbutils.types import ANTHROPIC_VERSION, cloud_protocol_headers

    # Anthropic rejects a request without it, for inference and the model list.
    assert cloud_protocol_headers("anthropic") == {"anthropic-version": ANTHROPIC_VERSION}
    assert cloud_protocol_headers("openai") == {}
    assert cloud_protocol_headers(None) == {}
