from unittest.mock import patch
from tests.modules.modeling.module_modeling_llm.mock.utils.mock_llm_config import (
    mock_get_llm_config,
)

patch(
    "llm_core.loaders.llm_config_loader.get_llm_config",
    mock_get_llm_config,
    create=True,
).start()

# Import OpenAI mocks first to ensure they're in place before any other imports
from tests.modules.modeling.module_modeling_llm.mock.utils.mock_openai import (
    mock_openai,
    mock_openai_client,
)

import pytest
import pytest_asyncio
import asyncio
from module_modeling_llm.config import BasicApproachConfig
from llm_core.models.openai import OpenAIModelConfig
from tests.modules.modeling.module_modeling_llm.mock.utils.mock_llm import (
    MockLanguageModel,
    MockAssessmentModel,
)
from tests.modules.modeling.module_modeling_llm.mock.utils.mock_config import (
    MockApproachConfig,
    MockModelConfig,
)
import json
from athena.modeling import Exercise, Submission
from athena.schemas.exercise_type import ExerciseType


@pytest_asyncio.fixture
async def mock_config():
    """Create a mock configuration for testing."""
    config = BasicApproachConfig(
        max_input_tokens=5000,
        model=OpenAIModelConfig(
            model_name="mock_model", get_model=lambda: MockLanguageModel()
        ),
    )
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

    def json(self):
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
    return Submission(id=1, exerciseId=mock_exercise.id, model=json.dumps(model_data))
