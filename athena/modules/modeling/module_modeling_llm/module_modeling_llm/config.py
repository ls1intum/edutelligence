from llm_core.models import ModelConfigType
from pydantic import BaseModel, Field
from typing import Optional

from athena import config_schema_provider
from module_modeling_llm.prompts import (
    graded_feedback_prompt,
    filter_feedback_prompt,
    structured_grading_instructions_prompt,
)


class GenerateSuggestionsPrompt(BaseModel):
    """
    Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**,
    **{bonus_points}**, **{submission}**

    _Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input
    is too long._
    """

    graded_feedback_system_message: str = Field(
        default=graded_feedback_prompt.graded_feedback_system_message,
        description="Message for priming AI behavior and instructing it what to do.",
    )
    graded_feedback_human_message: str = Field(
        default=graded_feedback_prompt.graded_feedback_human_message,
        description="Message from a human. The input on which the AI is supposed to act.",
    )
    filter_feedback_system_message: str = Field(
        default=filter_feedback_prompt.filter_feedback_system_message,
        description="Message for priming AI behavior for filtering ungraded feedback.",
    )
    filter_feedback_human_message: str = Field(
        default=filter_feedback_prompt.filter_feedback_human_message,
        description="Message for instructing AI to filter ungraded feedback.",
    )
    structured_grading_instructions_system_message: str = Field(
        default=structured_grading_instructions_prompt.structured_grading_instructions_system_message,
        description="Message for instructing AI to structure the Problem Statement",
    )
    structured_grading_instructions_human_message: str = Field(
        default=structured_grading_instructions_prompt.structured_grading_instructions_human_message,
        description="Message for instructing AI to filter ungraded feedback.",
    )


class BasicApproachConfig(BaseModel):
    """This approach uses a LLM with a single prompt to generate feedback in a single step."""

    max_input_tokens: int = Field(
        default=5000, description="Maximum number of tokens in the input prompt."
    )
    generate_feedback: Optional[ModelConfigType] = Field(
        default=None,
        title="Generate Feedback Provider",
        description="Select the LLM provider to use for generating feedback.",
    )
    filter_feedback: Optional[ModelConfigType] = Field(
        default=None,
        title="Filter Feedback Provider",
        description="Select the LLM provider to use for filtering feedback.",
    )
    review_feedback: Optional[ModelConfigType] = Field(
        default=None,
        title="Review Feedback Provider",
        description="Select the LLM provider to use for reviewing feedback.",
    )
    generate_grading_instructions: Optional[ModelConfigType] = Field(
        default=None,
        title="Generate Grading Instructions Provider",
        description="Select the LLM provider to use for generating grading instructions.",
    )
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(
        default=GenerateSuggestionsPrompt()
    )


@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: BasicApproachConfig = Field(
        default_factory=BasicApproachConfig,
        description="Configuration for the basic approach.",
    )
