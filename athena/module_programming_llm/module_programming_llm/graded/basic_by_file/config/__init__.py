from abc import ABC
from pydantic import BaseModel, Field

from module_programming_llm.helpers.models import ModelConfigType, DefaultModelConfig

from .generate import GradedFeedbackGenerationPrompt
from .split_grading_instructions import SplitGradingInstructionsPrompt
from .split_problem_statement import SplitProblemStatementPrompt


class GradedBasicByFileConfig(BaseModel, ABC):
    """\
This approach uses an LLM to split up the problem statement and grading instructions by file, if necessary. \
Then, it generates graded suggestions for each file independently.\
"""
    model: ModelConfigType = Field(default=DefaultModelConfig()) # type: ignore
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    max_number_of_files: int = Field(default=25, description="Maximum number of files. If exceeded, it will prioritize the most important ones.")
    
    generate_prompt: GradedFeedbackGenerationPrompt = Field(default=GradedFeedbackGenerationPrompt())
    split_grading_instructions_prompt: SplitGradingInstructionsPrompt = (Field(default=SplitGradingInstructionsPrompt()))
    split_problem_statement_prompt: SplitProblemStatementPrompt = Field(default=SplitProblemStatementPrompt())

