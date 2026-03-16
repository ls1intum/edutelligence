from abc import ABC
from pathlib import Path

from llm_core.loaders.llm_config_loader import get_llm_config
from pydantic import BaseModel, Field
from llm_core.models import ModelConfigType

from athena import config_schema_provider
from module_programming_quality_llm.prompts.generate_graded_suggestions_by_file import (
    system_message as generate_graded_suggestions_by_file_system_message,
    human_message as generate_graded_suggestions_by_file_human_message,
)
from module_programming_quality_llm.prompts.generate_non_graded_suggestions_by_file import (
    system_message as generate_non_graded_suggestions_by_file_system_message,
    human_message as generate_non_graded_suggestions_by_file_human_message,
)
from module_programming_quality_llm.prompts.split_grading_instructions_by_file import (
    system_message as split_grading_instructions_by_file_message,
    human_message as split_grading_instructions_by_file_human_message,
)
from module_programming_quality_llm.prompts.split_problem_non_grading_statement_by_file import (
    system_message as split_problem_statements_by_file_system_message_without_solution,
    human_message as split_problem_statements_by_file_human_message_without_solution,
)
from module_programming_quality_llm.prompts.split_problem_grading_statement_by_file import (
    system_message as split_problem_statements_by_file_system_message_with_solution,
    human_message as split_problem_statements_by_file_human_message_with_solution,
)
from module_programming_quality_llm.prompts.summarize_submission_by_file import (
    system_message as summarize_submission_by_file_system_message,
    human_message as summarize_submission_by_file_human_message,
)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "llm_config.yml"
llm_config = get_llm_config(str(_CONFIG_PATH))


class SplitProblemStatementsBasePrompt(BaseModel):
    """Base class for splitting problem statements into file-based ones, providing a structured approach for processing statements."""

    system_message: str = Field(
        ...,
        description="Message for priming AI behavior and instructing it what to do.",
    )
    human_message: str = Field(
        ...,
        description="Message for priming AI behavior and instructing it what to do.",
    )
    tokens_before_split: int = Field(
        default=250,
        description="Split the problem statement into file-based ones after this number of tokens.",
    )


class SplitProblemStatementsWithSolutionByFilePrompt(SplitProblemStatementsBasePrompt):
    """Specialized class for splitting problem statements with solutions, for cases where detailed solution information is available."""

    system_message: str = split_problem_statements_by_file_system_message_with_solution
    human_message: str = split_problem_statements_by_file_human_message_with_solution


class SplitProblemStatementsWithoutSolutionByFilePrompt(
    SplitProblemStatementsBasePrompt
):
    """Specialized class for splitting problem statements without solutions, applicable when solution details are not provided."""

    system_message: str = (
        split_problem_statements_by_file_system_message_without_solution
    )
    human_message: str = split_problem_statements_by_file_human_message_without_solution


class SplitGradingInstructionsByFilePrompt(BaseModel):
    """\
Features available: **{grading_instructions}**, **{changed_files_from_template_to_solution}**, **{changed_files_from_template_to_submission}**\
"""

    system_message: str = Field(
        default=split_grading_instructions_by_file_message,
        description="Message for priming AI behavior and instructing it what to do.",
    )
    human_message: str = Field(
        default=split_grading_instructions_by_file_human_message,
        description="Message from a human. The input on which the AI is supposed to act.",
    )
    tokens_before_split: int = Field(
        default=250,
        description="Split the grading instructions into file-based ones after this number of tokens.",
    )


class FeedbackGenerationBasePrompt(BaseModel):
    """Base class for feedback generation prompts, contains common definitions."""

    system_message: str = Field(
        ...,
        description="Message for priming AI behavior and instructing it what to do.",
    )
    human_message: str = Field(
        ...,
        description="Message from a human. The input on which the AI is supposed to act.",
    )


class GradedFeedbackGenerationPrompt(FeedbackGenerationBasePrompt):
    """Generates graded feedback based on file submissions, tailored to provide detailed, evaluative comments and scores."""

    system_message: str = generate_graded_suggestions_by_file_system_message
    human_message: str = generate_graded_suggestions_by_file_human_message


class NonGradedFeedbackGenerationPrompt(FeedbackGenerationBasePrompt):
    """\
Features available: **{problem_statement}**, **{submission_file}**

*Note: Prompt will be applied per file independently. Also, you don't have to include all features,
e.g. template_to_submission_diff.
    """

    system_message: str = generate_non_graded_suggestions_by_file_system_message
    human_message: str = generate_non_graded_suggestions_by_file_human_message


class FileSummaryPrompt(BaseModel):
    """Generates concise summaries of submission files, facilitating a quicker review and understanding of the content for AI processing."""

    system_message: str = Field(
        summarize_submission_by_file_system_message,
        description="Message for priming AI behavior and instructing it what to do.",
    )
    human_message: str = Field(
        summarize_submission_by_file_human_message,
        description="Message from a human. The input on which the AI is supposed to act.",
    )


class BasicApproachConfig(BaseModel):
    """Defines a basic configuration for processing submissions, incorporating problem statement splitting, feedback generation, and file summarization."""

    max_input_tokens: int = Field(
        default=1500, description="Maximum number of tokens in the input prompt."
    )
    model: ModelConfigType = Field(
        title="Model",
        description="The model to use for the approach.",
        default=llm_config.models.base_model_config,
    )
    max_number_of_files: int = Field(
        default=15,
        description="Maximum number of files. If exceeded, it will prioritize the most important ones.",
    )
    split_problem_statement_by_file_prompt: SplitProblemStatementsBasePrompt = Field(
        description="To be defined in " "subclasses."
    )
    generate_suggestions_by_file_prompt: SplitProblemStatementsBasePrompt = Field(
        description="To be defined in " "subclasses."
    )
    generate_file_summary_prompt: FileSummaryPrompt = Field(
        default=FileSummaryPrompt(
            system_message=summarize_submission_by_file_system_message,
            human_message=summarize_submission_by_file_human_message,
        ),
        description="Generates short summaries to be fed into the LLM with separate files.",
    )


class GradedBasicApproachConfig(BasicApproachConfig, ABC):
    """\
This approach uses an LLM to split up the problem statement and grading instructions by file, if necessary. \
Then, it generates graded suggestions for each file independently.\
"""

    split_problem_statement_by_file_prompt: (
        SplitProblemStatementsWithSolutionByFilePrompt
    ) = Field(default=SplitProblemStatementsWithSolutionByFilePrompt())
    split_grading_instructions_by_file_prompt: SplitGradingInstructionsByFilePrompt = (
        Field(default=SplitGradingInstructionsByFilePrompt())
    )
    generate_suggestions_by_file_prompt: FeedbackGenerationBasePrompt = Field(
        default=GradedFeedbackGenerationPrompt()
    )


class NonGradedBasicApproachConfig(BasicApproachConfig, ABC):
    """\
This approach uses an LLM to split up the problem statement, if necessary. \
Then, it generates non graded suggestions for each file independently.\
"""

    split_problem_statement_by_file_prompt: (
        SplitProblemStatementsWithoutSolutionByFilePrompt
    ) = Field(default=SplitProblemStatementsWithoutSolutionByFilePrompt())
    generate_suggestions_by_file_prompt: FeedbackGenerationBasePrompt = Field(
        default=NonGradedFeedbackGenerationPrompt()
    )


@config_schema_provider
class Configuration(BaseModel):
    """Configuration settings for the entire module, including debug mode and approach-specific configurations."""

    debug: bool = Field(default=False, description="Enable debug mode.")
    graded_approach: GradedBasicApproachConfig = Field(
        default=GradedBasicApproachConfig()
    )
    non_graded_approach: NonGradedBasicApproachConfig = Field(
        default=NonGradedBasicApproachConfig()
    )
