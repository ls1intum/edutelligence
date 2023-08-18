from pydantic import BaseModel, Field

from athena import config_schema_provider
from module_text_llm.helpers.models import ModelConfigType, DefaultModelConfig
from .prompts.suggest_feedback_basic import system_template, human_template


class BasicPrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{submission}**, **{max_points}**, **{bonus_points}**
**{problem_statement}** or **{example_solution}** might be omitted if the input is too long.\
"""
    system_message: str = Field(default=system_template,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_template,
                               description="Message from a human. The input on which the AI is supposed to act.")


class BasicApproachConfig(BaseModel):
    """This approach uses a LLM with a single prompt to generate feedback in a single step."""
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfigType = Field(default=DefaultModelConfig()) # type: ignore
    prompt: BasicPrompt = Field(default=BasicPrompt())


@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: BasicApproachConfig = Field(default=BasicApproachConfig())
