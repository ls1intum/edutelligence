# Patch get_llm_config before ANY other imports
import sys
from unittest.mock import patch
from tests.modules.text.utils.mock_llm_config import mock_get_llm_config

# Apply the patch globally before any modules are imported
# Use a more robust approach that handles CI environments
try:
    patch('llm_core.loaders.llm_config_loader.get_llm_config', mock_get_llm_config).start()
except (AttributeError, ModuleNotFoundError):
    # If the module isn't available yet, patch it when it gets imported
    patch('llm_core.loaders.llm_config_loader.get_llm_config', mock_get_llm_config, create=True).start()

# Import OpenAI mocks first to ensure they're in place before any other imports
from tests.modules.text.utils.mock_openai import mock_openai, mock_openai_client

import pytest
from tests.modules.text.utils.mock_llm import MockLanguageModel, MockStructuredMockLanguageModel, MockAssessmentModel
from tests.modules.text.utils.mock_config import MockApproachConfig, MockModelConfig
from tests.modules.text.utils.mock_env import mock_sent_tokenize


@pytest.fixture(autouse=True)
def patch_llm_config():
    """Automatically patch the get_llm_config function for all tests."""
    from unittest.mock import patch
    from tests.modules.text.utils.mock_llm_config import mock_get_llm_config
    
    with patch('module_text_llm.approach_config.get_llm_config', mock_get_llm_config):
        yield


@pytest.fixture
def mock_llm():
    """Fixture providing a basic mock language model."""
    return MockLanguageModel()


@pytest.fixture
def mock_structured_llm():
    """Fixture providing a structured mock language model."""
    return MockStructuredMockLanguageModel()


@pytest.fixture
def mock_assessment_model():
    """Fixture providing a mock assessment model."""
    return MockAssessmentModel()


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return MockApproachConfig(
        max_input_tokens=5000,
        model=MockModelConfig(),
        type="basic"
    )
