# Import OpenAI mocks first to ensure they're in place before any other imports
from tests.utils.mock_openai import mock_openai, mock_openai_client

import pytest
from tests.utils.mock_llm import MockLanguageModel, MockStructuredMockLanguageModel, MockAssessmentModel
from tests.utils.mock_config import MockApproachConfig, MockModelConfig
from tests.utils.mock_env import mock_sent_tokenize


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
