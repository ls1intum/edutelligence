import os
from typing import Type, Union, List
from module_programming_llm.helpers.models.model_config import ModelConfig


DefaultModelConfig: Type[ModelConfig]
default_model_name = os.environ.get("LLM_DEFAULT_MODEL")

types: List[Type[ModelConfig]] = []
try:
    import module_programming_llm.helpers.models.openai as openai_config
    types.append(openai_config.OpenAIModelConfig)
    if default_model_name in openai_config.available_models:
        DefaultModelConfig = openai_config.OpenAIModelConfig
except AttributeError:
    pass

try:
    import module_programming_llm.helpers.models.replicate as replicate_config
    types.append(replicate_config.ReplicateModelConfig)
    if default_model_name in replicate_config.available_models:
        DefaultModelConfig = replicate_config.ReplicateModelConfig
except AttributeError:
    pass

if not types:
    raise EnvironmentError(
        "No model configurations available, please set up at least one provider in the environment variables.")

if 'DefaultModelConfig' not in globals():
    DefaultModelConfig = types[0]

if len(types) == 1:
    ModelConfigType = types[0]
else:
    ModelConfigType = Union[tuple(types)]  # type: ignore
