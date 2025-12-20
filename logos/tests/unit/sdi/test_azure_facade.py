from unittest.mock import patch

import pytest

from logos.sdi.azure_facade import AzureSchedulingDataFacade
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
    status = facade.get_model_status(10)
    capacity = facade.get_capacity_info("azure", "gpt-4o")
    assert status.is_loaded is True
    assert status.queue_state is None
    assert capacity.has_capacity is True

    # Blocked
    headers_block = {
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-remaining-tokens": "0",
    }
    facade.update_rate_limits("azure", "gpt-4o", headers_block)
    capacity_block = facade.get_capacity_info("azure", "gpt-4o")
    assert capacity_block.has_capacity is False

    # Threshold (remaining <= 10 treated as no capacity in provider logic)
    headers_low = {
        "x-ratelimit-remaining-requests": "5",
        "x-ratelimit-remaining-tokens": "500",
    }
    facade.update_rate_limits("azure", "gpt-4o", headers_low)
    capacity_low = facade.get_capacity_info("azure", "gpt-4o")
    assert capacity_low.has_capacity is False

    # Recovered
    headers_ok = {
        "x-ratelimit-remaining-requests": "50",
        "x-ratelimit-remaining-tokens": "5000",
    }
    facade.update_rate_limits("azure", "gpt-4o", headers_ok)
    capacity_ok = facade.get_capacity_info("azure", "gpt-4o")
    # To simplify, we assume that having more than 10 remaining requests means capacity is available
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
