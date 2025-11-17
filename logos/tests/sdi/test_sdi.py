"""
Simple tests for Scheduling Data Interface (SDI) providers.

Tests OllamaDataProvider and AzureDataProvider with mocked responses.

Usage (recommended - runs in Docker automatically):

    ./tests/sdi/test_sdi.sh

Or run directly inside the logos-server container:

    docker compose exec logos-server poetry run pytest logos/tests/sdi/test_sdi.py -v
"""

import time
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock

import pytest
import requests

from logos.sdi.providers import OllamaDataProvider, AzureDataProvider


def test_ollama_provider_with_mock():
    """Test OllamaDataProvider with mocked /api/ps response."""

    # Mock /api/ps response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {
                "name": "llama2:7b",
                "size_vram": 4 * 1024 * 1024 * 1024,  # 4 GB
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat() + "Z"
            },
            {
                "name": "mixtral:8x7b",
                "size_vram": 12 * 1024 * 1024 * 1024,  # 12 GB
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat() + "Z"
            }
        ]
    }

    # Create provider
    provider = OllamaDataProvider(
        name="test-ollama",
        base_url="http://localhost:11434",
        total_vram_mb=18227,  # 17.8 GiB
        refresh_interval=5.0
    )

    # Register test models
    provider.register_model(1, "llama2:7b")
    provider.register_model(2, "mixtral:8x7b")

    # Mock requests.get
    with patch('requests.get', return_value=mock_response):
        provider.refresh_data()

    # Test get_model_status for loaded model
    status1 = provider.get_model_status(1)
    assert status1['model_id'] == 1
    assert status1['is_loaded'] == True
    assert status1['cold_start_predicted'] == False
    assert status1['vram_mb'] == 4096  # 4 GB
    assert status1['provider_type'] == 'ollama'

    # Test get_model_status for another loaded model
    status2 = provider.get_model_status(2)
    assert status2['model_id'] == 2
    assert status2['is_loaded'] == True
    assert status2['cold_start_predicted'] == False
    assert status2['vram_mb'] == 12288  # 12 GB

    # Test get_capacity_info
    capacity = provider.get_capacity_info()
    assert capacity['total_vram_mb'] == 18227
    assert capacity['loaded_models_count'] == 2
    assert 'llama2:7b' in capacity['loaded_models']
    assert 'mixtral:8x7b' in capacity['loaded_models']
    # Used: 4096 + 12288 = 16384 MB, Available: 18227 - 16384 = 1843 MB
    assert capacity['available_vram_mb'] == 1843
    assert capacity['can_load_new_model'] == False  # <4GB available

    print("✅ Ollama provider test passed")


def test_ollama_provider_unloaded_model():
    """Test OllamaDataProvider with model not in /api/ps (cold start)."""

    # Mock /api/ps with empty models
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": []}

    provider = OllamaDataProvider(
        name="test-ollama",
        base_url="http://localhost:11434",
        total_vram_mb=18227,
        refresh_interval=5.0
    )

    provider.register_model(1, "llama2:7b")

    with patch('requests.get', return_value=mock_response):
        provider.refresh_data()

    # Model not loaded - should predict cold start
    status = provider.get_model_status(1)
    assert status['is_loaded'] == False
    assert status['cold_start_predicted'] == True
    assert status['vram_mb'] == 0

    # Capacity should show all VRAM available
    capacity = provider.get_capacity_info()
    assert capacity['available_vram_mb'] == 18227
    assert capacity['loaded_models_count'] == 0
    assert capacity['can_load_new_model'] == True

    print("✅ Ollama unloaded model test passed")


def test_ollama_provider_expired_model():
    """Test OllamaDataProvider detects expiry from cached data without re-polling."""

    provider = OllamaDataProvider(
        name="test-ollama",
        base_url="http://localhost:11434",
        total_vram_mb=18227,
        refresh_interval=5.0  # Default: only refresh every 5 seconds
    )

    provider.register_model(1, "llama2:7b")

    # Step 1: Mock /api/ps - model expires in 1 second from now
    expires_in_1s = datetime.now(timezone.utc) + timedelta(seconds=1)
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {
                "name": "llama2:7b",
                "size_vram": 4 * 1024 * 1024 * 1024,
                "expires_at": expires_in_1s.isoformat() + "Z"
            }
        ]
    }

    with patch('requests.get', return_value=mock_response) as mock_get:
        provider.refresh_data()
        # Verify /api/ps was called once
        assert mock_get.call_count == 1

    # Step 2: Get status immediately (model not expired yet)
    status_before = provider.get_model_status(1)
    assert status_before['is_loaded'] == True
    assert status_before['cold_start_predicted'] == False
    print(f"  T+0s: is_loaded={status_before['is_loaded']}, cold_start={status_before['cold_start_predicted']}")

    # Step 3: Wait 3 seconds (model expires after 1s, but refresh_interval is 5s)
    time.sleep(3)

    # Step 4: Get status again
    # Should NOT poll /api/ps again (only 3 seconds passed, refresh_interval is 5s)
    # But SHOULD detect expiry based on cached expires_at vs current time
    with patch('requests.get', return_value=mock_response) as mock_get:
        status_after = provider.get_model_status(1)
        # Verify /api/ps was NOT called again (using cached data)
        assert mock_get.call_count == 0

    assert status_after['is_loaded'] == False
    assert status_after['cold_start_predicted'] == True
    print(f"  T+3s: is_loaded={status_after['is_loaded']}, cold_start={status_after['cold_start_predicted']} (no /api/ps poll)")

    print("✅ Ollama expired model test passed (expiry detected from cached data)")


def test_azure_provider():
    """Test AzureDataProvider with per-deployment rate limit tracking."""

    provider = AzureDataProvider()

    # Register test model with deployment name
    provider.register_model(10, "gpt-4o", deployment_name="gpt-4o")

    # Mock response headers from Azure OpenAI (based on real API response)
    mock_headers = {
        'x-ratelimit-remaining-requests': '999',
        'x-ratelimit-remaining-tokens': '999994',
        'x-ratelimit-limit-requests': '1000',
        'x-ratelimit-limit-tokens': '1000000'
    }

    # Update rate limits for specific deployment
    provider.update_rate_limits("gpt-4o", mock_headers)

    # Test get_capacity_info for this deployment
    capacity = provider.get_capacity_info("gpt-4o")
    assert capacity['deployment_name'] == 'gpt-4o'
    assert capacity['rate_limit_remaining_requests'] == 999
    assert capacity['rate_limit_remaining_tokens'] == 999994
    assert capacity['rate_limit_total_requests'] == 1000
    assert capacity['rate_limit_total_tokens'] == 1000000
    assert capacity['has_capacity'] == True  # >10 requests remaining
    assert capacity['last_header_age_seconds'] is not None  # Should have timestamp
    assert capacity['last_header_age_seconds'] < 1  # Very recent

    # Test get_model_status - cloud models are always available
    status = provider.get_model_status(10)
    assert status['model_id'] == 10
    assert status['is_loaded'] == True
    assert status['cold_start_predicted'] == False
    assert status['vram_mb'] == 0  # No VRAM constraints in cloud
    assert status['provider_type'] == 'azure'

    print("✅ Azure provider test passed")


def test_azure_provider_low_quota():
    """Test AzureDataProvider with low remaining quota."""

    provider = AzureDataProvider()
    provider.register_model(10, "gpt-4o", deployment_name="gpt-4o")

    # Mock headers with low remaining quota
    mock_headers = {
        'x-ratelimit-remaining-requests': '5',  # Only 5 remaining
        'x-ratelimit-remaining-tokens': '1000'
    }

    provider.update_rate_limits("gpt-4o", mock_headers)

    capacity = provider.get_capacity_info("gpt-4o")
    assert capacity['rate_limit_remaining_requests'] == 5
    assert capacity['has_capacity'] == False  # <=10 requests remaining

    print("✅ Azure low quota test passed")


def test_azure_provider_multiple_deployments():
    """Test that different deployments have separate rate limit tracking."""

    provider = AzureDataProvider()

    # Register two different deployments
    provider.register_model(10, "gpt-4o", deployment_name="gpt-4o")
    provider.register_model(12, "o3-mini", deployment_name="o3-mini")

    # Update rate limits for deployment A (gpt-4o)
    headers_gpt4 = {
        'x-ratelimit-remaining-requests': '950',
        'x-ratelimit-remaining-tokens': '990000',
        'x-ratelimit-limit-requests': '1000',
        'x-ratelimit-limit-tokens': '1000000'
    }
    provider.update_rate_limits("gpt-4o", headers_gpt4)

    # Update rate limits for deployment B (o3-mini) with different values
    headers_o3 = {
        'x-ratelimit-remaining-requests': '450',
        'x-ratelimit-remaining-tokens': '450000',
        'x-ratelimit-limit-requests': '500',
        'x-ratelimit-limit-tokens': '500000'
    }
    provider.update_rate_limits("o3-mini", headers_o3)

    # Verify deployment A has its own limits
    capacity_gpt4 = provider.get_capacity_info("gpt-4o")
    assert capacity_gpt4['deployment_name'] == 'gpt-4o'
    assert capacity_gpt4['rate_limit_remaining_requests'] == 950
    assert capacity_gpt4['rate_limit_total_requests'] == 1000

    # Verify deployment B has separate limits (not affected by deployment A)
    capacity_o3 = provider.get_capacity_info("o3-mini")
    assert capacity_o3['deployment_name'] == 'o3-mini'
    assert capacity_o3['rate_limit_remaining_requests'] == 450
    assert capacity_o3['rate_limit_total_requests'] == 500

    # Critical check: deployments don't share quota!
    assert capacity_gpt4['rate_limit_remaining_requests'] != capacity_o3['rate_limit_remaining_requests']

    print("✅ Azure multiple deployments test passed")


def test_ollama_queue_tracking():
    """Test queue depth tracking for Ollama provider."""

    provider = OllamaDataProvider(
        name="test-ollama",
        base_url="http://localhost:11434",
        total_vram_mb=18227,
        refresh_interval=5.0
    )

    provider.register_model(1, "llama2:7b")

    # Test queue operations
    assert provider.get_queue_depth(1) == 0 

    provider.increment_queue(1)
    assert provider.get_queue_depth(1) == 1

    provider.increment_queue(1)
    provider.increment_queue(1)
    assert provider.get_queue_depth(1) == 3

    provider.decrement_queue(1)
    assert provider.get_queue_depth(1) == 2

    provider.decrement_queue(1)
    provider.decrement_queue(1)
    assert provider.get_queue_depth(1) == 0

    # Should not go negative
    provider.decrement_queue(1)
    assert provider.get_queue_depth(1) == 0

    print("✅ Queue tracking test passed")


def test_ollama_provider_real():
    """
    Test with real Ollama instance (host or localhost).

    This test tries to connect to Ollama in the following order:
    1. host.docker.internal:11434 (when running inside Docker container)
    2. localhost:11434 (when running on host machine)

    This test is skipped if Ollama is not accessible.

    To run Ollama locally:
    1. Download from https://ollama.com
    2. Start: `ollama serve` (runs on http://127.0.0.1:11434 by default)
    3. Pull a model: `ollama pull llama2:7b`
    """

    # Try to find Ollama (Docker first, then local fallback)
    ollama_urls = [
        "http://host.docker.internal:11434",  # Docker container
        "http://localhost:11434"              # Local testing
    ]

    base_url = None
    for url in ollama_urls:
        try:
            response = requests.get(f"{url}/api/ps", timeout=2.0)
            if response.status_code == 200:
                base_url = url
                break
        except requests.exceptions.RequestException:
            continue

    if base_url is None:
        pytest.skip("Ollama not accessible (tried: Docker host and localhost)")

    # Create provider with real Ollama
    provider = OllamaDataProvider(
        name="localhost-ollama",
        base_url=base_url,
        total_vram_mb=18227,  # 17.8 GiB from M4 Pro
        refresh_interval=5.0
    )

    # Refresh data from real Ollama
    provider.refresh_data()

    # Test get_capacity_info
    capacity = provider.get_capacity_info()
    assert capacity['total_vram_mb'] == 18227
    assert capacity['available_vram_mb'] >= 0
    assert capacity['loaded_models_count'] >= 0
    assert isinstance(capacity['loaded_models'], list)

    print(f"✅ Real Ollama test passed - connected to {base_url}")
    print(f"   Models loaded: {capacity['loaded_models_count']}")
    print(f"   Available VRAM: {capacity['available_vram_mb']} MB")
    if capacity['loaded_models']:
        print(f"   Loaded models: {', '.join(capacity['loaded_models'])}")


if __name__ == "__main__":
    # Run tests
    print("========================================================================")
    print("Testing SDI Providers")
    print("========================================================================")
    print("")

    test_ollama_provider_with_mock()
    test_ollama_provider_unloaded_model()
    test_ollama_provider_expired_model()
    test_azure_provider()
    test_azure_provider_low_quota()
    test_ollama_queue_tracking()

    print("")
    print("Testing with real Ollama (if available)...")
    try:
        test_ollama_provider_real()
    except Exception as e:
        print(f"⚠️  Real Ollama test skipped: {e}")

    print("")
    print("========================================================================")
    print("✅ All tests passed!")
    print("========================================================================")
