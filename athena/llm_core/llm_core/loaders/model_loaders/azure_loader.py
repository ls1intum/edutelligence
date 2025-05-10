from enum import Enum
import os
import requests
from typing import Dict, List

from langchain.base_language import BaseLanguageModel
from langchain_openai import AzureChatOpenAI

from athena.logger import logger


# Discover available models from Azure 
AZURE_OPENAI_PREFIX = "azure_openai_"
azure_available = bool(os.environ.get("AZURE_OPENAI_API_KEY"))

azure_available_models: Dict[str, BaseLanguageModel] = {}

# Azure OpenAI
if azure_available:
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
        azure_available_models[AZURE_OPENAI_PREFIX + deployment] = AzureChatOpenAI(azure_deployment=deployment)


if azure_available_models:
    logger.info("Available azure models: %s", ", ".join(azure_available_models.keys()))
else:
    logger.warning("No azure models discovered.")

# Enum for referencing the discovered models
if azure_available_models:
    AzureModel = Enum('AzureModel', {name: name for name in azure_available_models})  # type: ignore
else:
    class AzureModel(str, Enum):
        pass