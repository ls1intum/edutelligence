from pydantic import BaseModel, Field

from athena import config_schema_provider
from module_programming_llm.helpers.models import ModelConfigType, DefaultModelConfig
from module_programming_llm.prompts.generate_suggestions_by_file import (
    system_template as generate_suggestions_by_file_system_template,
    human_template as generate_suggestions_by_file_human_template
) 
from module_programming_llm.prompts.split_grading_instructions_by_file import (
    system_template as split_grading_instructions_by_file_template, 
    human_template as split_grading_instructions_by_file_human_template
)
from module_programming_llm.prompts.split_problem_statement_by_file import (
    system_template as split_problem_statements_by_file_system_template,
    human_template as split_problem_statements_by_file_human_template
)


class SplitProblemStatementsByFilePrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{changed_files_from_template_to_solution}**, **{changed_files_from_template_to_submission}**

*Note: `changed_files` are the changed files between template and solution repository.*\
"""
    tokens_before_split: int = Field(default=250, description="Split the problem statement into file-based ones after this number of tokens.")
    system_message: str = Field(default=split_problem_statements_by_file_system_template,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=split_problem_statements_by_file_human_template,
                               description="Message from a human. The input on which the AI is supposed to act.")


class SplitGradingInstructionsByFilePrompt(BaseModel):
    """\
Features available: **{grading_instructions}**, **{changed_files_from_template_to_solution}**, **{changed_files_from_template_to_submission}**
"""
    tokens_before_split: int = Field(default=250, description="Split the grading instructions into file-based ones after this number of tokens.")
    system_message: str = Field(default=split_grading_instructions_by_file_template,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=split_grading_instructions_by_file_human_template,
                               description="Message from a human. The input on which the AI is supposed to act.")


class GenerationPrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, \
**{submission_file}**, **{solution_to_submission_diff}**, **{template_to_submission_diff}**, **{template_to_solution_diff}**

*Note: Prompt will be applied per file independently. Also, you don't have to include all features, e.g. template_to_solution_diff.*\
"""
    system_message: str = Field(default=generate_suggestions_by_file_system_template,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=generate_suggestions_by_file_human_template,
                               description="Message from a human. The input on which the AI is supposed to act.")


class BasicApproachConfig(BaseModel):
    """This approach uses a LLM with a single prompt to generate feedback in a single step."""
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfigType = Field(default=DefaultModelConfig())  # type: ignore
    
    max_number_of_files: int = Field(default=25, description="Maximum number of files.")
    split_problem_statement_by_file_prompt: SplitProblemStatementsByFilePrompt = Field(default=SplitProblemStatementsByFilePrompt())
    split_grading_instructions_by_file_prompt: SplitGradingInstructionsByFilePrompt = Field(default=SplitGradingInstructionsByFilePrompt())
    generate_suggestions_by_file_prompt: GenerationPrompt = Field(default=GenerationPrompt())


@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: BasicApproachConfig = Field(default=BasicApproachConfig())
