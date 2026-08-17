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
