import pytest
from typing import List, Optional, Dict
from dataclasses import dataclass

from tests.modules.programming.module_programming_llm.mock.utils.mock_module_config import (
    GradedBasicApproachConfig,
    NonGradedBasicApproachConfig,
)
from tests.modules.programming.module_programming_llm.mock.utils.mock_config import (
    MockModelConfig,
    create_mock_graded_config,
    create_mock_non_graded_config,
)

@dataclass
class MockFeedback:
    
    exercise_id: int
    submission_id: int
    title: str
    description: str
    file_path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    credits: Optional[float] = None
    is_graded: bool = False
    meta: Dict = None

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}

async def mock_generate_graded_suggestions(exercise, submission, config) -> List[MockFeedback]:
    if not submission.files:
        return []
        
    return [
        MockFeedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title="Logic Error",
            description="Doc important",
            file_path="test.py",
            line_start=1,
            line_end=1,
            credits=0.5,
            is_graded=True,
            meta={},
        )
    ]

async def mock_generate_non_graded_suggestions(exercise, submission, config) -> List[MockFeedback]:
    
    if not submission.files:
        return []
    return [
        MockFeedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title="Logic Error",
            description="Doc important",
            file_path="test.py",
            line_start=1,
            line_end=1,
            is_graded=False,
            meta={},
        )
    ]

@pytest.mark.asyncio
async def test_generate_graded_suggestions(mock_exercise, mock_submission):
    model_config = MockModelConfig()
    config = create_mock_graded_config(model_config)
    feedbacks = await mock_generate_graded_suggestions(mock_exercise, mock_submission, config)
    
    assert feedbacks is not None, "Feedbacks should not be None"
    assert len(feedbacks) == 1, "Should have one feedback"
    feedback = feedbacks[0]
    assert feedback.title == "Logic Error"
    assert feedback.description == "Doc important"
    assert feedback.credits == 0.5
    assert feedback.is_graded is True
    assert feedback.file_path == "test.py"
    assert feedback.line_start == 1
    assert feedback.line_end == 1

@pytest.mark.asyncio
async def test_generate_non_graded_suggestions(mock_exercise, mock_submission):
    model_config = MockModelConfig()
    config = create_mock_non_graded_config(model_config)
    feedbacks = await mock_generate_non_graded_suggestions(mock_exercise, mock_submission, config)
    
    assert feedbacks is not None, "Feedbacks should not be None"
    assert len(feedbacks) == 1, "Should have one feedback"
    feedback = feedbacks[0]
    assert feedback.title == "Logic Error"
    assert feedback.description == "Doc important"
    assert feedback.is_graded is False
    assert feedback.file_path == "test.py"
    assert feedback.line_start == 1
    assert feedback.line_end == 1

@pytest.mark.asyncio
async def test_error_handling(mock_exercise, mock_empty_submission):
    model_config = MockModelConfig()
    config = create_mock_graded_config(model_config)
    feedbacks = await mock_generate_graded_suggestions(mock_exercise, mock_empty_submission, config)
    
    assert feedbacks is not None
    assert len(feedbacks) == 0
