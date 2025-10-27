import pytest
from unittest.mock import patch
from module_text_llm.default_approach.generate_suggestions import generate_suggestions
from athena.text import Exercise, Submission, Feedback
from athena.schemas.exercise_type import ExerciseType
from modules.text.module_text_llm.mock.utils.mock_env import mock_sent_tokenize
from modules.text.module_text_llm.mock.utils.mock_llm import MockAssessmentModel, MockFeedbackModel
from athena.schemas.text_submission import TextLanguageEnum


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
        grading_criteria=[],
        meta={},
    )


@pytest.fixture
def mock_submission(mock_exercise):
    """Create a mock submission for testing."""
    return Submission(
        id=1,
        exercise_id=mock_exercise.id,
        text="This is a test submission.\nIt has multiple lines.\nFor testing purposes.",
        language=TextLanguageEnum.ENGLISH,
        meta={},
    )


@pytest.mark.asyncio
async def test_generate_suggestions_default(mock_exercise, mock_submission, mock_config):
    """Test default feedback generation with a simple submission."""
    mock_result = MockAssessmentModel(
        feedbacks=[
            MockFeedbackModel(
                title="Test Feedback",
                description="Test description",
                line_start=1,
                line_end=2,
                credits=5.0,
            )
        ]
    )

    # Patch the predict_and_parse function to return our mock result
    with patch(
        "module_text_llm.default_approach.generate_suggestions.predict_and_parse",
        return_value=mock_result,
    ):
        mock_sent_tokenize.return_value = [
            "This is a test submission.",
            "It has multiple lines.",
            "For testing purposes.",
        ]

        feedbacks = await generate_suggestions(
            exercise=mock_exercise,
            submission=mock_submission,
            config=mock_config,
            debug=False,
            is_graded=False,
            learner_profile=None,
            latest_submission=None,
        )

        assert isinstance(feedbacks, list)
        assert all(isinstance(feedback, Feedback) for feedback in feedbacks)
        assert all(feedback.exercise_id == mock_exercise.id for feedback in feedbacks)
        assert all(
            feedback.submission_id == mock_submission.id for feedback in feedbacks
        )


@pytest.mark.asyncio
async def test_generate_suggestions_empty_submission(mock_exercise, mock_config):
    """Test feedback generation with an empty submission."""
    empty_submission = Submission(id=2, exerciseId=mock_exercise.id, text="")
    mock_result = MockAssessmentModel(feedbacks=[])

    # Patch the predict_and_parse function to return our mock result
    with patch(
        "module_text_llm.default_approach.generate_suggestions.predict_and_parse",
        return_value=mock_result,
    ):
        mock_sent_tokenize.return_value = []

        feedbacks = await generate_suggestions(
            exercise=mock_exercise,
            submission=empty_submission,
            config=mock_config,
            debug=False,
            is_graded=False,
            learner_profile=None,
            latest_submission=None,
        )

        assert isinstance(feedbacks, list)
        assert len(feedbacks) == 0


@pytest.mark.asyncio
async def test_generate_suggestions_long_input(mock_exercise, mock_config):
    """Test feedback generation with a long submission."""
    long_submission = Submission(
        id=3,
        exercise_id=mock_exercise.id,
        text="Test " * 1000,
        language=TextLanguageEnum.ENGLISH,
        meta={},
    )
    mock_result = MockAssessmentModel(
        feedbacks=[
            MockFeedbackModel(
                title="Test Long Input Feedback",
                description="Test description for long input",
                line_start=1,
                line_end=100,
                credits=7.0,
            )
        ]
    )

    # Patch the predict_and_parse function to return our mock result
    with patch(
        "module_text_llm.default_approach.generate_suggestions.predict_and_parse",
        return_value=mock_result,
    ):
        mock_sent_tokenize.return_value = ["Test " * 100 for _ in range(10)]

        feedbacks = await generate_suggestions(
            exercise=mock_exercise,
            submission=long_submission,
            config=mock_config,
            debug=False,
            is_graded=False,
            learner_profile=None,
            latest_submission=None,
        )

        assert isinstance(feedbacks, list)
        assert all(isinstance(feedback, Feedback) for feedback in feedbacks)
        assert all(feedback.exercise_id == mock_exercise.id for feedback in feedbacks)
        assert all(
            feedback.submission_id == long_submission.id for feedback in feedbacks
        )
