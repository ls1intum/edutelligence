import os
from pydantic import BaseModel, Field
from typing import Union

from athena import config_schema_provider
from .prompts.suggest_feedback_basic import system_template, human_template


DefaultModelConfig = None
default_model_name = os.environ.get("LLM_DEFAULT_MODEL")

types = []
try:
    import module_text_llm.helpers.models.openai as openai_config
    types.append(openai_config.OpenAIModelConfig) # type: ignore
    if default_model_name in openai_config.available_models:
        DefaultModelConfig = openai_config.OpenAIModelConfig
except AttributeError:
    pass

try:
    import module_text_llm.helpers.models.replicate as replicate_config
    types.append(replicate_config.ReplicateModelConfig) # type: ignore
    if default_model_name in replicate_config.available_models:
        DefaultModelConfig = replicate_config.ReplicateModelConfig # type: ignore
except AttributeError:
    pass

if not types:
    raise EnvironmentError("No model configurations available, please set up at least one provider in the environment variables.")

if DefaultModelConfig is None:
    DefaultModelConfig = types[0]

if len(types) == 1:
    ModelConfig = types[0]
else:
    ModelConfig = Union[tuple(types)]  # type: ignore


class BasicPrompt(BaseModel):
    """Features available: **{problem_statement}**, **{grading_instructions}**, **{submission}**, **{max_points}**, **{bonus_points}**"""
    system_message: str = Field(default=system_template,
                                description="A Message for priming AI behavior, usually passed in as the first of a sequence of input messages.")
    human_message: str = Field(default=human_template,
                               description="A Message from a human. Usually the input on which the AI is supposed to act.")


class BasicApproachConfig(BaseModel):
    """This approach uses a LLM with a single prompt to generate feedback in a single step."""
    model: ModelConfig = Field(default=DefaultModelConfig()) # type: ignore
    prompt: BasicPrompt = Field(default=BasicPrompt())


@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: BasicApproachConfig = Field(default=BasicApproachConfig())
