"""Test suite for the text LLM module's basic approach functionality."""

from tests.utils.mock_env import mock_sent_tokenize
import sys
from unittest.mock import Mock, patch

# ---- Patch llm_core.models.openai ----
from pydantic import BaseModel, Field
from typing import Callable, Any

class MockOpenAIModelConfig(BaseModel):
    """Mock configuration for OpenAI model settings."""
    model_name: str = "mock_model"
    get_model: Callable[[], Any] = Field(default_factory=lambda: Mock())

    class Config:
        arbitrary_types_allowed = True

mock_openai = Mock()
mock_openai.OpenAIModelConfig = MockOpenAIModelConfig
mock_openai.available_models = {'mock_model': Mock()}
sys.modules['llm_core.models.openai'] = mock_openai

# ---- Patch configparser.ConfigParser ----
import configparser

class MockConfigParser:
    """Mock implementation of ConfigParser for module configuration."""
    def __init__(self):
        self._data = {"module": {"name": "text", "type": "text", "port": "8000"}}

    def __getitem__(self, key):
        return self._data[key]

    def read(self, *args, **kwargs):
        pass

# Start the patch context before other imports
patcher = patch("athena.module_config.configparser.ConfigParser", return_value=MockConfigParser())
patcher.start()

# Import test dependencies
import pytest
from module_text_llm.basic_approach.generate_suggestions import generate_suggestions
from athena.text import Exercise, Submission, Feedback
from module_text_llm.approach_config import ApproachConfig
from athena.schemas.exercise_type import ExerciseType

from tests.utils.mock_llm import MockLanguageModel, AssessmentModel, MockFeedbackModel
from tests.utils.mock_config import MockApproachConfig, MockModelConfig
from tests.utils.mock_env import mock_sent_tokenize


@pytest.fixture
def mock_exercise():
    """Create a mock exercise for testing."""
    return Exercise(
        id=1,
        title="Test Exercise",
        type=ExerciseType.text,
        max_points=10,
        bonus_points=2,
        grading_instructions="Test grading instructions",
        problem_statement="Test problem statement",
        example_solution="Test example solution",
        grading_criteria=[]
    )

@pytest.fixture
def mock_submission(mock_exercise):
    """Create a mock submission for testing."""
    return Submission(
        id=1,
        exerciseId=mock_exercise.id,
        text="This is a test submission.\nIt has multiple lines.\nFor testing purposes."
    )

@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return MockApproachConfig(
        max_input_tokens=5000,
        model=MockModelConfig(),
        type="basic"
    )

@pytest.mark.asyncio
async def test_generate_suggestions_basic(mock_exercise, mock_submission, mock_config):
    """Test basic feedback generation with a simple submission."""
    mock_model = MockLanguageModel(return_value=AssessmentModel(feedbacks=[
        MockFeedbackModel(
            title="Test Feedback",
            description="Test description",
            line_start=1,
            line_end=2,
            credits=5.0
        )
    ]))
    mock_config.model.get_model = lambda: mock_model
    mock_sent_tokenize.return_value = [
        "This is a test submission.",
        "It has multiple lines.",
        "For testing purposes."
    ]

    feedbacks = await generate_suggestions(
        exercise=mock_exercise,
        submission=mock_submission,
        config=mock_config,
        debug=False,
        is_graded=True
    )

    assert isinstance(feedbacks, list)
    assert all(isinstance(feedback, Feedback) for feedback in feedbacks)
    assert all(feedback.exercise_id == mock_exercise.id for feedback in feedbacks)
    assert all(feedback.submission_id == mock_submission.id for feedback in feedbacks)

@pytest.mark.asyncio
async def test_generate_suggestions_empty_submission(mock_exercise, mock_config):
    """Test feedback generation with an empty submission."""
    empty_submission = Submission(
        id=2,
        exerciseId=mock_exercise.id,
        text=""
    )
    mock_model = MockLanguageModel(return_value=AssessmentModel(feedbacks=[]))
    mock_config.model.get_model = lambda: mock_model
    mock_sent_tokenize.return_value = []

    feedbacks = await generate_suggestions(
        exercise=mock_exercise,
        submission=empty_submission,
        config=mock_config,
        debug=False,
        is_graded=True
    )

    assert isinstance(feedbacks, list)
    assert len(feedbacks) == 0

@pytest.mark.asyncio
async def test_generate_suggestions_long_input(mock_exercise, mock_config):
    """Test feedback generation with a long submission."""
    long_submission = Submission(
        id=3,
        exerciseId=mock_exercise.id,
        text="Test " * 1000
    )
    mock_model = MockLanguageModel(return_value=AssessmentModel(feedbacks=[
        MockFeedbackModel(
            title="Test Long Input Feedback",
            description="Test description for long input",
            line_start=1,
            line_end=100,
            credits=7.0
        )
    ]))
    mock_config.model.get_model = lambda: mock_model
    mock_sent_tokenize.return_value = ["Test " * 100 for _ in range(10)]

    feedbacks = await generate_suggestions(
        exercise=mock_exercise,
        submission=long_submission,
        config=mock_config,
        debug=False,
        is_graded=True
    )

    assert isinstance(feedbacks, list)
    assert all(isinstance(feedback, Feedback) for feedback in feedbacks)
    assert all(feedback.exercise_id == mock_exercise.id for feedback in feedbacks)
    assert all(feedback.submission_id == long_submission.id for feedback in feedbacks)
