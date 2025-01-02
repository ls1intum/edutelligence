import os
from llm_core.loaders.llm_capabilities_loader import get_model_capabilities
import openai
import requests

from typing import Dict, List
from enum import Enum
from pydantic import Field, PrivateAttr, validator, PositiveInt
from langchain.base_language import BaseLanguageModel
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from athena.logger import logger


# Discover available models from OpenAI / Azure 
OPENAI_PREFIX = "openai_"
AZURE_OPENAI_PREFIX = "azure_openai_"
openai_available = bool(os.environ.get("OPENAI_API_KEY"))
azure_openai_available = bool(os.environ.get("AZURE_OPENAI_API_KEY"))

available_models: Dict[str, BaseLanguageModel] = {}

# OpenAI
if openai_available:
    openai.api_type = "openai"
    for model in openai.models.list():
        if "gpt" in model.id or "o1" in model.id:
            available_models[OPENAI_PREFIX + model.id] = ChatOpenAI(model=model.id)


# Azure OpenAI
if azure_openai_available:
    def _get_azure_openai_deployments() -> List[str]:
        base_url = f"{os.environ.get('AZURE_OPENAI_ENDPOINT')}/openai"
        headers = {"api-key": os.environ["AZURE_OPENAI_API_KEY"]}

        models_response = requests.get(
            f"{base_url}/models?api-version=2023-03-15-preview",
            headers=headers, timeout=30
        )
        models_data = models_response.json()["data"]

        deployments_response = requests.get(
            f"{base_url}/deployments?api-version=2023-03-15-preview",
            headers=headers, timeout=30
        )
        deployments_data = deployments_response.json()["data"]

        # If deployment["model"] is substring of model["id"], we consider it a chat completion model
        chat_completion_models = ",".join(
            m["id"] for m in models_data if m["capabilities"]["chat_completion"]
        )
        return [
            d["id"]
            for d in deployments_data
            if d["model"] in chat_completion_models
        ]

    for deployment in _get_azure_openai_deployments():
        available_models[AZURE_OPENAI_PREFIX + deployment] = AzureChatOpenAI(azure_deployment=deployment)


if available_models:
    logger.info("Available openai models: %s", ", ".join(available_models.keys()))
else:
    logger.warning("No openai/azure models discovered.")

# Enum for referencing the discovered models
if available_models:
    OpenAIModel = Enum('OpenAIModel', {name: name for name in available_models})  # type: ignore
else:
    class OpenAIModel(str, Enum):
        pass