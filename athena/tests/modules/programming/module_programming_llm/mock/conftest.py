import pytest
from pydantic import ConfigDict, Field
from typing import Any, Dict, List, Optional, Type
from unittest.mock import Mock, patch
from athena.programming import Exercise, Submission
from athena.schemas.exercise_type import ExerciseType
from module_programming_llm.config import (
    Configuration,
    GradedBasicApproachConfig,
    NonGradedBasicApproachConfig,
)
from langchain_community.chat_models.fake import FakeListChatModel
from langchain_core.pydantic_v1 import BaseModel
from llm_core.models.providers.openai_model_config import OpenAIModelConfig
from module_programming_llm.config import (
    SplitProblemStatementsWithSolutionByFilePrompt,
    SplitGradingInstructionsByFilePrompt,
    GradedFeedbackGenerationPrompt,
    FileSummaryPrompt,
    SplitProblemStatementsWithoutSolutionByFilePrompt,
    NonGradedFeedbackGenerationPrompt,
)
from module_programming_llm.prompts.summarize_submission_by_file import (
    system_message as summarize_system_message,
    human_message as summarize_human_message,
)
from llm_core.models import ModelConfigType


class FakeChatModel(FakeListChatModel):
    """A fake chat model for testing purposes"""

    requests: List[Dict] = Field(default_factory=list)
    responses: List[Any] = Field(default_factory=list)
    pydantic_object: Optional[Type[BaseModel]] = None

    def get_model(self):
        return self


class FakeModelConfig(OpenAIModelConfig):
    """A fake ModelConfig that extends OpenAIModelConfig for testing"""

    model_name: str = "fake_model"

    def get_model(self, openai_catalog=None):
        """Override to return our fake model"""
        return FakeChatModel()

    model_config = ConfigDict(arbitrary_types_allowed=True)


@pytest.fixture(autouse=True)
def mock_get_repository():
    mock_repo = Mock()
    mock_repo.git.show.return_value = "def main():\n    pass"
    with patch(
        "athena.helpers.programming.code_repository.get_repository",
        return_value=mock_repo,
    ) as mock:
        yield mock


@pytest.fixture
def mock_exercise():
    """Provides a mock programming exercise"""
    exercise_data = {
        "id": 1,
        "title": "Test Programming Exercise",
        "type": ExerciseType.programming,
        "max_points": 10.0,
        "bonus_points": 0.0,
        "grading_instructions": "It should do nothing.",
        "grading_criteria": [],
        "problem_statement": "Create a main function.",
        "meta": {},
        "programming_language": "python",
        "solution_repository_uri": "http://mock.test/solution",
        "template_repository_uri": "http://mock.test/template",
        "tests_repository_uri": "http://mock.test/tests",
    }
    return Exercise.parse_obj(exercise_data)


@pytest.fixture
def mock_submission():
    """Provides a mock programming submission"""
    return Submission(
        id=1, exercise_id=1, repository_uri="http://mock.test/submission", meta={}
    )


@pytest.fixture
def mock_empty_submission():
    """Provides a mock empty submission for error handling tests"""
    return Submission(
        id=2, exercise_id=1, repository_uri="http://mock.test/empty_submission", meta={}
    )


@pytest.fixture
def mock_configuration():
    """Provides a mock configuration object for the programming module"""
    # Use FakeModelConfig which is a valid Pydantic model
    fake_model_config = FakeModelConfig(
        model_name="fake_model",
        provider="openai",
        max_tokens=4000,
        temperature=0.0,
        top_p=1.0,
        presence_penalty=0.0,
        frequency_penalty=0.0,
    )

    graded_approach = GradedBasicApproachConfig(
        model=fake_model_config,
        split_problem_statement_by_file_prompt=SplitProblemStatementsWithSolutionByFilePrompt(),
        split_grading_instructions_by_file_prompt=SplitGradingInstructionsByFilePrompt(),
        generate_suggestions_by_file_prompt=GradedFeedbackGenerationPrompt(),
        generate_file_summary_prompt=FileSummaryPrompt(
            system_message=summarize_system_message,
            human_message=summarize_human_message,
        ),
    )

    non_graded_approach = NonGradedBasicApproachConfig(
        model=fake_model_config,
        split_problem_statement_by_file_prompt=SplitProblemStatementsWithoutSolutionByFilePrompt(),
        generate_suggestions_by_file_prompt=NonGradedFeedbackGenerationPrompt(),
        generate_file_summary_prompt=FileSummaryPrompt(
            system_message=summarize_system_message,
            human_message=summarize_human_message,
        ),
    )

    return Configuration(
        debug=True,
        graded_approach=graded_approach,
        non_graded_approach=non_graded_approach,
    )
