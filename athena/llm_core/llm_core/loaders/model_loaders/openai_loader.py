from enum import Enum
import os
import openai
from typing import Dict

from langchain.base_language import BaseLanguageModel
from langchain_openai import ChatOpenAI

from athena.logger import logger


# Discover available models from OpenAI
OPENAI_PREFIX = "openai_"
openai_available = bool(os.environ.get("OPENAI_API_KEY"))

openai_available_models: Dict[str, BaseLanguageModel] = {}

# OpenAI
if openai_available:
    openai.api_type = "openai"
    for model in openai.models.list():
        if "gpt" in model.id or "o1" in model.id:
            openai_available_models[OPENAI_PREFIX + model.id] = ChatOpenAI(model=model.id)


if openai_available_models:
    logger.info("Available openai models: %s", ", ".join(openai_available_models.keys()))
else:
    logger.warning("No openai models discovered.")

# Enum for referencing the discovered models
if openai_available_models:
    OpenAIModel = Enum('OpenAIModel', {name: name for name in openai_available_models})  # type: ignore
else:
    class OpenAIModel(str, Enum):
        pass