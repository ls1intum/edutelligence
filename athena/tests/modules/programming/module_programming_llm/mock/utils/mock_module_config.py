import sys
from unittest.mock import Mock, patch
from pydantic import BaseModel
from typing import Any
import pytest
from athena.module_config import ModuleConfig
from athena.schemas.exercise_type import ExerciseType

# Mock the module config
mock_config = ModuleConfig(
    name="module_programming_llm",
    type=ExerciseType.programming,
    port=5002
)

# Create mock config classes
class SplitProblemStatementsWithSolutionByFilePrompt(BaseModel):
    system_message: str
    human_message: str
    tokens_before_split: int

class SplitProblemStatementsWithoutSolutionByFilePrompt(BaseModel):
    system_message: str
    human_message: str
    tokens_before_split: int

class SplitGradingInstructionsByFilePrompt(BaseModel):
    system_message: str
    human_message: str
    tokens_before_split: int

class GradedFeedbackGenerationPrompt(BaseModel):
    system_message: str
    human_message: str
    tokens_before_split: int

class NonGradedFeedbackGenerationPrompt(BaseModel):
    system_message: str
    human_message: str
    tokens_before_split: int

class FileSummaryPrompt(BaseModel):
    system_message: str
    human_message: str

class GradedBasicApproachConfig(BaseModel):
    max_input_tokens: int
    model: Any = None
    max_number_of_files: int
    split_problem_statement_by_file_prompt: SplitProblemStatementsWithSolutionByFilePrompt
    split_grading_instructions_by_file_prompt: SplitGradingInstructionsByFilePrompt
    generate_suggestions_by_file_prompt: GradedFeedbackGenerationPrompt
    generate_file_summary_prompt: FileSummaryPrompt

class NonGradedBasicApproachConfig(BaseModel):
    max_input_tokens: int
    model: Any = None
    max_number_of_files: int
    split_problem_statement_by_file_prompt: SplitProblemStatementsWithoutSolutionByFilePrompt
    generate_suggestions_by_file_prompt: NonGradedFeedbackGenerationPrompt
    generate_file_summary_prompt: FileSummaryPrompt

class Configuration(BaseModel):
    debug: bool = False
    graded_approach: GradedBasicApproachConfig
    non_graded_approach: NonGradedBasicApproachConfig

# Create mock module function instead of globally overwriting sys.modules
def create_mock_module():
    """Create a mock module for use in fixtures instead of globally overwriting sys.modules."""
    mock_module = Mock()
    mock_module.GradedBasicApproachConfig = GradedBasicApproachConfig
    mock_module.NonGradedBasicApproachConfig = NonGradedBasicApproachConfig
    mock_module.Configuration = Configuration
    mock_module.SplitProblemStatementsWithSolutionByFilePrompt = SplitProblemStatementsWithSolutionByFilePrompt
    mock_module.SplitProblemStatementsWithoutSolutionByFilePrompt = SplitProblemStatementsWithoutSolutionByFilePrompt
    mock_module.SplitGradingInstructionsByFilePrompt = SplitGradingInstructionsByFilePrompt
    mock_module.GradedFeedbackGenerationPrompt = GradedFeedbackGenerationPrompt
    mock_module.NonGradedFeedbackGenerationPrompt = NonGradedFeedbackGenerationPrompt
    mock_module.FileSummaryPrompt = FileSummaryPrompt
    return mock_module

@pytest.fixture(autouse=True)
def mock_module_config():
    with patch("athena.module_config.get_module_config", return_value=mock_config) as mock:
        yield mock 