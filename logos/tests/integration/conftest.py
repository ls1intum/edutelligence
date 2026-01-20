"""
Pytest configuration for integration tests.
Provides fixtures for database, HTTP client, mocks, and verification helpers.
"""

import pytest
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient
from unittest.mock import MagicMock, Mock


def pytest_addoption(parser):
    """Register custom CLI options for test configuration."""
    parser.addoption(
        "--api-base",
        action="store",
        default="http://localhost:8000",
        help="Base URL for Logos API (default: http://localhost:8000)"
    )


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def logos_key():
    """Get mock logos API key for testing."""
    # All dependencies are mocked, so we use a mock key
    return "lg-test-mock-key-for-integration-tests"


@pytest.fixture(scope="session")
def api_base(request):
    """Get API base URL."""
    return request.config.getoption("--api-base", default="http://localhost:8000")


@pytest.fixture
async def logos_client(api_base) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for Logos API."""
    async with AsyncClient(base_url=api_base, timeout=30.0) as client:
        yield client


# ============================================================================
# MOCK DATABASE FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def mock_providers_data():
    """Mock provider data for testing."""
    return [
        {
            "id": 1,
            "name": "azure-test-provider",
            "base_url": "https://test-azure.openai.azure.com/openai/deployments",
            "provider_type": "azure",
            "api_key": "mock-azure-key"
        },
        {
            "id": 2,
            "name": "openwebui-test-provider",
            "base_url": "http://localhost:11434",
            "provider_type": "openwebui",
            "api_key": "mock-openwebui-key"
        }
    ]


@pytest.fixture(scope="session")
def mock_models_data(mock_providers_data):
    """Mock model data for testing."""
    return [
        {
            "id": 1,
            "name": "gpt-4",
            "deployment_name": "gpt-4-deployment",
            "provider_id": 1,
            "provider_name": "azure-test-provider",
            "provider_base_url": mock_providers_data[0]["base_url"],
            "provider_type": "azure",
            "context_window": 8192,
            "max_tokens": 4096
        },
        {
            "id": 2,
            "name": "gpt-35-turbo",
            "deployment_name": "gpt-35-turbo-deployment",
            "provider_id": 1,
            "provider_name": "azure-test-provider",
            "provider_base_url": mock_providers_data[0]["base_url"],
            "provider_type": "azure",
            "context_window": 4096,
            "max_tokens": 2048
        },
        {
            "id": 3,
            "name": "llama3:8b",
            "deployment_name": "llama3:8b",
            "provider_id": 2,
            "provider_name": "openwebui-test-provider",
            "provider_base_url": mock_providers_data[1]["base_url"],
            "provider_type": "openwebui",
            "context_window": 8192,
            "max_tokens": 4096
        }
    ]


@pytest.fixture(scope="session")
def test_models(mock_models_data):
    """Organize test models by provider type."""
    azure_models = [m for m in mock_models_data if m["provider_type"] == "azure"]
    openwebui_models = [m for m in mock_models_data if m["provider_type"] == "openwebui"]

    return {
        "azure": azure_models,
        "openwebui": openwebui_models,
        "all": mock_models_data
    }


@pytest.fixture
def azure_test_model(test_models):
    """Get a single Azure model for testing."""
    return test_models["azure"][0]


@pytest.fixture
def openwebui_test_model(test_models):
    """Get a single OpenWebUI model for testing."""
    return test_models["openwebui"][0]


class MockDBManager:
    """Mock DBManager for testing that returns predefined data."""

    def __init__(self, mock_providers_data, mock_models_data):
        self.providers = {p["id"]: p for p in mock_providers_data}
        self.models = {m["id"]: m for m in mock_models_data}
        self.request_logs = {}
        self.monitoring_events = {}
        self.jobs = {}
        self._request_id_counter = 1000

    def get_provider(self, provider_id: int):
        """Get provider by ID."""
        return self.providers.get(provider_id)

    def get_provider_to_model(self, model_id: int):
        """Get provider for a model."""
        model = self.models.get(model_id)
        if model:
            return self.providers.get(model["provider_id"])
        return None

    def get_all_models_data(self):
        """Get all models."""
        return list(self.models.values())

    def get_all_models(self):
        """Get all models (alternative method name)."""
        return list(self.models.values())

    def get_request_log(self, request_id: int):
        """Get request log by ID."""
        return self.request_logs.get(request_id, {
            "id": request_id,
            "request_id": request_id,
            "status": "completed",
            "classification_duration": None,
            "scheduling_duration": None,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30
        })

    def get_monitoring_events(self, request_id: int):
        """Get monitoring events for a request."""
        return self.monitoring_events.get(request_id, [])

    def get_job(self, job_id: int):
        """Get job by ID."""
        return self.jobs.get(job_id, {
            "job_id": job_id,
            "status": "success",
            "created_at": "2024-01-01T00:00:00Z",
            "completed_at": "2024-01-01T00:00:01Z"
        })


@pytest.fixture
def mock_db(mock_providers_data, mock_models_data, mocker):
    """Mock DBManager for all tests."""
    mock_db_instance = MockDBManager(mock_providers_data, mock_models_data)

    # Patch DBManager to return our mock
    mocker.patch(
        "logos.dbutils.dbmanager.DBManager",
        return_value=mock_db_instance
    )

    return mock_db_instance


@pytest.fixture
def db_manager(mock_db):
    """Database manager for test queries (uses mock)."""
    return mock_db


@pytest.fixture
def verification(mock_db):
    """Verification helpers for assertions."""
    from .fixtures.verification import VerificationHelper
    return VerificationHelper(mock_db)


# ============================================================================
# MOCK PROVIDER FIXTURES
# ============================================================================

@pytest.fixture
def mock_providers(respx_mock):
    """Mock provider endpoints (Azure, OpenWebUI)."""
    try:
        from .fixtures.mock_providers import ProviderMocker
        return ProviderMocker(respx_mock)
    except ImportError:
        # respx not installed, skip
        pytest.skip("respx not installed - run: poetry add --group dev respx")


@pytest.fixture
def mock_sdi(mocker):
    """Mock Ollama /ps endpoint."""
    from .fixtures.mock_sdi import SDIMocker
    return SDIMocker(mocker)


# ============================================================================
# TEST LIFECYCLE
# ============================================================================

@pytest.fixture(autouse=True)
def reset_queue_between_tests():
    """Reset queue state between tests."""
    # Queue state is already isolated in Logos server
    # No cleanup needed for integration tests
    yield
