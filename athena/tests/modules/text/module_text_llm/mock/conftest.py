from unittest.mock import patch
import pytest
from athena.module_config import ModuleConfig
from athena.schemas.exercise_type import ExerciseType

stub = ModuleConfig(name="module_text_llm", type=ExerciseType.text, port=5001)
patch("athena.module_config.get_module_config", return_value=stub).start()

from modules.modeling.module_modeling_llm.mock.utils.mock_llm_config import (
    mock_get_llm_config,
)
from modules.text.module_text_llm.mock.utils.mock_llm import (
    MockLanguageModel,
    MockStructuredMockLanguageModel,
    MockAssessmentModel,
)
from modules.text.module_text_llm.mock.utils.mock_config import MockApproachConfig


@pytest.fixture(autouse=True)
def _mock_llm_config(monkeypatch):
    monkeypatch.setattr(
        "llm_core.loaders.llm_config_loader.get_llm_config",
        mock_get_llm_config,
    )


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
        max_input_tokens=5000, model={"provider": "stub"}, type="default"
    )
