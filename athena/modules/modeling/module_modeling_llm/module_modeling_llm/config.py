from pydantic import BaseModel, Field

from athena import config_schema_provider
from module_modeling_llm.helpers.models import ModelConfigType, DefaultModelConfig
from module_modeling_llm.prompts.generate_suggestions import (
    graded_feedback_system_message,
    graded_feedback_human_message,
    filter_feedback_system_message,
    filter_feedback_human_message
)


class GenerateSuggestionsPrompt(BaseModel):
    """
    Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**,
    **{bonus_points}**, **{submission}**

    _Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input
    is too long._
    """
    graded_feedback_system_message: str = Field(default=graded_feedback_system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    graded_feedback_human_message: str = Field(default=graded_feedback_human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
    filter_feedback_system_message: str = Field(default=filter_feedback_system_message,
                                description="Message for priming AI behavior for filtering ungraded feedback.")
    filter_feedback_human_message: str = Field(default=filter_feedback_human_message,
                               description="Message for instructing AI to filter ungraded feedback.")
    


class BasicApproachConfig(BaseModel):
    """This approach uses a LLM with a single prompt to generate feedback in a single step."""
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfigType = Field(default=DefaultModelConfig())  # type: ignore
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())


@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: BasicApproachConfig = Field(default=BasicApproachConfig())
