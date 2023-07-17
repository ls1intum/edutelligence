from pydantic import BaseModel, Field

from athena import config_schema_provider
from module_text_llm.helpers.models.openai import OpenAIModelConfig
from .prompts.suggest_feedback_basic import system_template, human_template


class BasicPrompt(BaseModel):
    """Features available: **{problem_statement}**, **{grading_instructions}**, **{submission}**, **{max_points}**, **{bonus_points}**"""
    system_message: str = Field(default=system_template,
                                description="A Message for priming AI behavior, usually passed in as the first of a sequence of input messages.")
    human_message: str = Field(default=human_template,
                               description="A Message from a human. Usually the input on which the AI is supposed to act.")


class BasicApproachConfig(BaseModel):
    """This approach uses a LLM with a single prompt to generate feedback in a single step."""
    model: OpenAIModelConfig = Field(default=OpenAIModelConfig()) # type: ignore
    prompt: BasicPrompt = Field(default=BasicPrompt())


@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: BasicApproachConfig = Field(default=BasicApproachConfig())
