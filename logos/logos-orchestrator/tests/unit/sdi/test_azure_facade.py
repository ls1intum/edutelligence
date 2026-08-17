from logos import AzureSchedulingDataFacade
from logos.sdi.providers.azure_provider import AzureDataProvider


def test_azure_facade_status_and_capacity_updates():
    facade = AzureSchedulingDataFacade()
    facade.register_model(
        10,
        "azure",
        "azure-gpt-4-omni",
        "https://example.com/openai/deployments/gpt-4o/chat/completions",
        provider_id=2,
    )

    # Initial: no rate-limit info -> has capacity
    status = facade.get_model_status(10, provider_id=2)
    capacity = facade.get_capacity_info(2, "gpt-4o")
    assert status.is_loaded is True
    assert status.queue_state is None
    assert capacity.has_capacity is True

    # Blocked
    headers_block = {
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-remaining-tokens": "0",
    }
    facade.update_rate_limits(2, "gpt-4o", headers_block)
    capacity_block = facade.get_capacity_info(2, "gpt-4o")
    assert capacity_block.has_capacity is False

    # Low headroom remains routable; the scheduler applies a wait penalty.
    headers_low = {
        "x-ratelimit-remaining-requests": "5",
        "x-ratelimit-remaining-tokens": "500",
    }
    facade.update_rate_limits(2, "gpt-4o", headers_low)
    capacity_low = facade.get_capacity_info(2, "gpt-4o")
    assert capacity_low.has_capacity is True

    # Either Azure quota dimension can independently block the deployment.
    facade.update_rate_limits(
        2,
        "gpt-4o",
        {
            "x-ratelimit-remaining-requests": "5",
            "x-ratelimit-remaining-tokens": "0",
        },
    )
    assert facade.get_capacity_info(2, "gpt-4o").has_capacity is False

    facade.update_rate_limits(
        2,
        "gpt-4o",
        {
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-remaining-tokens": "500",
        },
    )
    assert facade.get_capacity_info(2, "gpt-4o").has_capacity is False

    # Recovered
    headers_ok = {
        "x-ratelimit-remaining-requests": "50",
        "x-ratelimit-remaining-tokens": "5000",
    }
    facade.update_rate_limits(2, "gpt-4o", headers_ok)
    capacity_ok = facade.get_capacity_info(2, "gpt-4o")
    assert capacity_ok.has_capacity is True
    assert capacity_ok.rate_limit_remaining_requests == 50


def test_azure_provider_lookup_and_defaults(monkeypatch):
    provider = AzureDataProvider(name="azure")
    provider.register_model(1, "gpt-4o", "gpt-4o")
    status = provider.get_model_status(1)
    assert status.is_loaded is True
    assert status.queue_state is None

    cap = provider.get_capacity_info("gpt-4o")
    assert cap.deployment_name == "gpt-4o"
    assert cap.has_capacity is True


def test_azure_capacity_exhaustion_expires_per_quota_dimension(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("logos.sdi.providers.azure_provider.time.time", lambda: now[0])
    provider = AzureDataProvider(name="azure")

    provider.update_rate_limits(
        "gpt-4o",
        {
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-remaining-tokens": "0",
        },
    )
    assert provider.get_capacity_info("gpt-4o").has_capacity is False

    # A later response that omits the token quota must not make the old token
    # snapshot fresh again.
    now[0] = 130.0
    provider.update_rate_limits("gpt-4o", {"x-ratelimit-remaining-requests": "5"})
    assert provider.get_capacity_info("gpt-4o").has_capacity is False

    now[0] = 161.0
    capacity = provider.get_capacity_info("gpt-4o")
    assert capacity.has_capacity is True
    assert capacity.rate_limit_remaining_requests == 5
    assert capacity.rate_limit_remaining_tokens is None
