from pydantic import BaseModel, Field

from athena import config_schema_provider
from module_modelling_llm.helpers.models import ModelConfigType, DefaultModelConfig
from module_modelling_llm.prompts.generate_suggestions import (
    system_message as generate_suggestions_system_message,
    human_message as generate_suggestions_human_message
)


class GenerateSuggestionsPrompt(BaseModel):
    """
    Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**,
    **{bonus_points}**, **{submission}**

    _Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input
    is too long._
    """
    system_message: str = Field(default=generate_suggestions_system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=generate_suggestions_human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")


class BasicApproachConfig(BaseModel):
    """This approach uses a LLM with a single prompt to generate feedback in a single step."""
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfigType = Field(default=DefaultModelConfig())  # type: ignore
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())


@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: BasicApproachConfig = Field(default=BasicApproachConfig())
