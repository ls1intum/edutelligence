from unittest.mock import patch, MagicMock
import pytest
import pytest_asyncio
import json
from athena.module_config import ModuleConfig
from athena.schemas.exercise_type import ExerciseType

stub = ModuleConfig(name="module_modeling_llm", type=ExerciseType.modeling, port=5001)
patch("athena.module_config.get_module_config", return_value=stub).start()


from modules.modeling.module_modeling_llm.mock.utils.mock_llm import (
    MockLanguageModel,
    MockAssessmentModel,
)
from athena.modeling import Exercise, Submission
from utils.mock_llm_config import mock_get_llm_config


@pytest.fixture(autouse=True)
def _mock_llm_config(monkeypatch):
    monkeypatch.setattr(
        "llm_core.loaders.llm_config_loader.get_llm_config",
        mock_get_llm_config,
    )


class MockModelConfig:
    """Mock model configuration that doesn't raise errors."""
    
    def get_model(self):
        # Return a mock model that doesn't raise an error
        from unittest.mock import Mock
        mock_model = Mock()
        mock_model.name = "mock-model"
        return mock_model
    
    def supports_system_messages(self):
        return True
    
    def supports_function_calling(self):
        return True
    
    def supports_structured_output(self):
        return True


@pytest_asyncio.fixture
async def mock_config():
    """
    Create a flexible mock configuration for testing using MagicMock.
    This avoids issues with Pydantic model validation and field assignment.
    """
    config = MagicMock()
    config.generate_feedback = MockModelConfig()
    config.generate_suggestions_prompt = MagicMock()

    return config


@pytest.fixture
def mock_llm():
    """Fixture providing a basic mock language model."""
    return MockLanguageModel()


@pytest.fixture
def mock_assessment_model():
    """Fixture providing a mock assessment model."""
    return MockAssessmentModel()


class MockPrompt:
    def __init__(
        self,
        graded_feedback_system_message="Test system message",
        graded_feedback_human_message="Test human message",
    ):
        self.graded_feedback_system_message = graded_feedback_system_message
        self.graded_feedback_human_message = graded_feedback_human_message


class MockStructuredGradingCriterion:
    def __init__(self):
        self.criteria = [
            {
                "id": "1",
                "title": "Class Structure",
                "description": "Classes should have appropriate attributes and methods",
                "max_points": 5.0,
            },
            {
                "id": "2",
                "title": "Relationships",
                "description": "Relationships between classes should be correctly modeled",
                "max_points": 5.0,
            },
        ]

    def model_dump_json(self):
        return json.dumps(self.criteria)


@pytest.fixture
def mock_grading_criterion():
    """Create a mock structured grading criterion."""
    return MockStructuredGradingCriterion()


@pytest.fixture
def mock_exercise():
    """Create a mock exercise for testing."""
    example_solution = {
        "type": "class",
        "elements": {
            "1": {"id": "1", "type": "class", "name": "User", "attributes": ["2", "3"]},
            "2": {"id": "2", "type": "attribute", "name": "name"},
            "3": {"id": "3", "type": "attribute", "name": "password"},
            "4": {
                "id": "4",
                "type": "class",
                "name": "Order",
                "attributes": ["5", "6"],
            },
            "5": {"id": "5", "type": "attribute", "name": "orderId"},
            "6": {"id": "6", "type": "attribute", "name": "date"},
        },
        "relationships": {
            "1": {
                "id": "1",
                "type": "association",
                "source": {"element": "1"},
                "target": {"element": "4"},
            }
        },
    }
    return Exercise(
        id=1,
        title="Test Exercise",
        type=ExerciseType.modeling,
        max_points=10,
        bonus_points=2,
        grading_instructions="Test grading instructions",
        problem_statement="Test problem statement",
        example_solution=json.dumps(example_solution),
        grading_criteria=[],
        meta={},
    )


@pytest.fixture
def mock_submission(mock_exercise):
    """Create a mock submission for testing."""
    model_data = {
        "type": "class",
        "elements": {
            "1": {"id": "1", "type": "class", "name": "User", "attributes": ["2", "3"]},
            "2": {"id": "2", "type": "attribute", "name": "name"},
            "3": {"id": "3", "type": "attribute", "name": "password"},
            "4": {
                "id": "4",
                "type": "class",
                "name": "Order",
                "attributes": ["5", "6"],
            },
            "5": {"id": "5", "type": "attribute", "name": "orderId"},
            "6": {"id": "6", "type": "attribute", "name": "date"},
        },
        "relationships": {
            "1": {
                "id": "1",
                "type": "association",
                "source": {"element": "1"},
                "target": {"element": "4"},
            }
        },
    }
    return Submission(
        id=1, exercise_id=mock_exercise.id, model=json.dumps(model_data), meta={}
    )
