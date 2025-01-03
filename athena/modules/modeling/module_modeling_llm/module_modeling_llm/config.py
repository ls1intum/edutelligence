from llm_core.loaders.llm_config_loader import get_llm_config
from llm_core.models import ModelConfigType
from pydantic import BaseModel, Field

from athena import config_schema_provider
from llm_core.models.model_config import ModelConfig
from module_modeling_llm.prompts import (
    graded_feedback_prompt,
    filter_feedback_prompt,
    structured_grading_instructions_prompt
)

llm_config = get_llm_config()

class GenerateSuggestionsPrompt(BaseModel):
    """
    Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**,
    **{bonus_points}**, **{submission}**

    _Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input
    is too long._
    """
    graded_feedback_system_message: str = Field(
        default=graded_feedback_prompt.graded_feedback_system_message,
        description="Message for priming AI behavior and instructing it what to do."
    )
    graded_feedback_human_message: str = Field(
        default=graded_feedback_prompt.graded_feedback_human_message,
        description="Message from a human. The input on which the AI is supposed to act."
    )
    filter_feedback_system_message: str = Field(
        default=filter_feedback_prompt.filter_feedback_system_message,
        description="Message for priming AI behavior for filtering ungraded feedback."
    )
    filter_feedback_human_message: str = Field(
        default=filter_feedback_prompt.filter_feedback_human_message,
        description="Message for instructing AI to filter ungraded feedback."
    )
    structured_grading_instructions_system_message: str = Field(
        default=structured_grading_instructions_prompt.structured_grading_instructions_system_message,
        description="Message for instructing AI to structure the Problem Statement"
    )
    structured_grading_instructions_human_message: str = Field(
        default=structured_grading_instructions_prompt.structured_grading_instructions_human_message,
        description="Message for instructing AI to filter ungraded feedback."
    )

class BasicApproachConfig(BaseModel):
    """This approach uses a LLM with a single prompt to generate feedback in a single step."""
    max_input_tokens: int = Field(default=5000, description="Maximum number of tokens in the input prompt.")
    generate_feedback: ModelConfigType = Field(default=llm_config.models.base_model_config)
    filter_feedback: ModelConfigType = Field(default=llm_config.models.base_model_config)
    review_feedback: ModelConfigType = Field(default=llm_config.models.fast_reasoning_model_config)
    generate_grading_instructions: ModelConfigType = Field(default=llm_config.models.base_model_config)
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())

@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: BasicApproachConfig = Field(default=BasicApproachConfig())