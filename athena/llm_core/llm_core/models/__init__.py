import os
from typing import Type, Union, List, Optional
from langchain.base_language import BaseLanguageModel

from llm_core.models.model_config import ModelConfig
from athena.logger import logger

DefaultModelConfig: Type[ModelConfig]
MiniModelConfig: ModelConfig
OllamaModelConfig: ModelConfig
default_model_name = os.environ.get("LLM_DEFAULT_MODEL")
evaluation_model_name = os.environ.get("LLM_EVALUATION_MODEL")

# Model used during evaluation for judging the output (should be a more powerful model)
evaluation_model: Optional[BaseLanguageModel] = None

types: List[Type[ModelConfig]] = []
try:
    import llm_core.models.openai as openai_config
    types.append(openai_config.OpenAIModelConfig)
    if default_model_name in openai_config.available_models:
        DefaultModelConfig = openai_config.OpenAIModelConfig
    if evaluation_model_name in openai_config.available_models:
        logger.info("Evaluation model: %s", evaluation_model_name)
        for model in openai_config.available_models:
            logger.info("Available openai models: %s", model)
        evaluation_model = openai_config.available_models[evaluation_model_name]
except AttributeError:
    pass

try:
    import llm_core.models.ollama as ollama_config #type: ignore
    types.append(ollama_config.OllamaModelConfig)
    OllamaModelConfig = ollama_config.OllamaModelConfig(model_name="llama3.1:70b",max_tokens=1000, temperature=0,top_p=1,presence_penalty=0,frequency_penalty=0)
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