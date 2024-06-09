from abc import ABC
from pydantic import BaseModel, Field

from module_programming_llm.helpers.models import ModelConfigType, DefaultModelConfig

from .generate import GuidedFeedbackGenerationPrompt
from .split_problem_statement import SplitProblemStatementPrompt
from .summarize_submission import FileSummaryPrompt


class GuidedBasicByFileConfig(BaseModel, ABC):
    """\
    This approach uses an LLM to split up the problem statement, if necessary. 
    Then, it generates non graded suggestions for each file independently.\
    """

    model: ModelConfigType = Field(default=DefaultModelConfig()) # type: ignore
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    max_number_of_files: int = Field(default=25, description="Maximum number of files. If exceeded, it will prioritize the most important ones.")
    
    generate_prompt: GuidedFeedbackGenerationPrompt = Field(default=GuidedFeedbackGenerationPrompt())
    split_problem_statement_prompt: SplitProblemStatementPrompt = (Field(default=SplitProblemStatementPrompt()))
    summarize_submission_prompt: FileSummaryPrompt = Field(default=FileSummaryPrompt())
