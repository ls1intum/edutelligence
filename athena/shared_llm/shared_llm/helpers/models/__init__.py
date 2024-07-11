import os
from typing import Type, Union, List, Optional
from langchain.base_language import BaseLanguageModel

from shared_llm.helpers.models.model_config import ModelConfig

DefaultModelConfig: Type[ModelConfig]
default_model_name = os.environ.get("LLM_DEFAULT_MODEL")
evaluation_model_name = os.environ.get("LLM_EVALUATION_MODEL")

# Model used during evaluation for judging the output (should be a more powerful model)
evaluation_model: Optional[BaseLanguageModel] = None

types: List[Type[ModelConfig]] = []
try:
    import shared_llm.helpers.models.openai as openai_config
    types.append(openai_config.OpenAIModelConfig)
    if default_model_name in openai_config.available_models:
        DefaultModelConfig = openai_config.OpenAIModelConfig
    if evaluation_model_name in openai_config.available_models:
        evaluation_model = openai_config.available_models[evaluation_model_name]
except AttributeError:
    pass

try:
    import shared_llm.helpers.models.replicate as replicate_config
    types.append(replicate_config.ReplicateModelConfig)
    if default_model_name in replicate_config.available_models:
        DefaultModelConfig = replicate_config.ReplicateModelConfig
    if evaluation_model_name in replicate_config.available_models:
        evaluation_model = replicate_config.available_models[evaluation_model_name]
except AttributeError:
    pass

try:
    import shared_llm.helpers.models.llama as ollama_config
    types.append(ollama_config.OllamaModelConfig)
    # DefaultModelConfig = ollama_config.OllamaModelConfig
except AttributeError:
    pass


if not types:
    raise EnvironmentError(
        "No model configurations available, please set up at least one provider in the environment variables.")

if 'DefaultModelConfig' not in globals():
    DefaultModelConfig = types[0]

type0 = types[0]
if len(types) == 1:
    ModelConfigType = type0
else:
    type1 = types[1]
    ModelConfigType = Union[type0, type1] # type: ignore
