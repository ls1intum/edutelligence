from abc import ABC

from pydantic import BaseModel, Field

from module_programming_llm.helpers.models import ModelConfigType, DefaultModelConfig
from athena import config_schema_provider
from module_programming_llm.prompts import SplitProblemStatementByFile, SplitGradingInstructionsByFile, \
    GenerateSuggestionsByFile, GenerateFileSummary
from module_programming_llm.prompts.filter_out_solution.filter_out_solution import FilterOutSolution
from module_programming_llm.prompts.generate_grading_criterion.generate_grading_criterion import \
    GenerateGradingCriterion
from module_programming_llm.prompts.validate_suggestions import ValidateSuggestions


class BasicApproachConfig(BaseModel):
    """Defines a basic configuration for processing submissions, incorporating problem statement splitting, feedback generation."""

    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfigType = Field(default=DefaultModelConfig())  # type: ignore


class BasicByFileApproachConfig(BasicApproachConfig, ABC):
    """
    This approach uses an LLM to split up the problem statement and grading instructions by file, if necessary.
    Then, it generates graded suggestions for each file independently.
    Generates grading instructions if not available.
    Validates and filters out generated feedback.
    """

    split_problem_statement_by_file: SplitProblemStatementByFile = Field(default=SplitProblemStatementByFile())
    split_grading_instructions_by_file: SplitGradingInstructionsByFile = (
        Field(default=SplitGradingInstructionsByFile()))
    generate_suggestions_by_file: GenerateSuggestionsByFile = Field(default=GenerateSuggestionsByFile())
    generate_file_summary: GenerateFileSummary = Field(default=GenerateFileSummary())
    filter_out_solution: FilterOutSolution = Field(default=FilterOutSolution())
    validate_suggestions: ValidateSuggestions = Field(default=ValidateSuggestions())
    generate_grading_criterion: GenerateGradingCriterion = Field(default=GenerateGradingCriterion())
    max_number_of_files: int = Field(default=25,
                                     description="Maximum number of files. If exceeded, it will prioritize the most important ones.")
    tokens_before_split: int = Field(default=250,
                                     description="Split the grading instructions into file-based ones after this number of tokens.")


# class ZeroShotApproachConfig(BasicApproachConfig, ABC):
#     """\
# This approach uses an LLM to split up the problem statement, if necessary. \
# Then, it generates non graded suggestions for each file independently.\
# """
#
#     split_problem_statement_by_file_prompt: SplitProblemStatementsWithoutSolutionByFilePrompt = Field(default=SplitProblemStatementsWithoutSolutionByFilePrompt())
#     generate_suggestions_by_file_prompt: FeedbackGenerationBasePrompt = Field(default=NonGradedFeedbackGenerationPrompt())
#     split_grading_instructions_by_file_prompt: SplitGradingInstructionsByFilePrompt = (Field(default=SplitGradingInstructionsByFilePrompt()))
#
#
@config_schema_provider
class Configuration(BaseModel):
    """Configuration settings for the entire module, including debug mode and approach-specific configurations."""

    debug: bool = Field(default=False, description="Enable debug mode.")
    basic_by_file_approach: BasicByFileApproachConfig = Field(default=BasicByFileApproachConfig())
    # zero_shot_approach: ZeroShotApproachConfig = Field(default=ZeroShotApproachConfig())
