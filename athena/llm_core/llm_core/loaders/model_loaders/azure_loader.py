from __future__ import annotations

import requests
from enum import Enum
from types import MappingProxyType
from typing import Dict, List, Tuple
from langchain.base_language import BaseLanguageModel
from langchain_openai import AzureChatOpenAI

from athena.logger import logger
from athena.settings import LLMSettings
from llm_core.catalog import ModelCatalog


AZURE_OPENAI_PREFIX = "azure_openai_"


def _get_azure_openai_deployments(
    endpoint: str, api_key: str, api_version: str
) -> Tuple[List[dict], List[str]]:
    base_url = f"{endpoint}/openai"
    headers = {"api-key": api_key}

    models_resp = requests.get(
        f"{base_url}/models",
        params={"api-version": api_version},
        headers=headers,
        timeout=30,
    )
    models_resp.raise_for_status()
    models_data = models_resp.json()["data"]

    deployments_resp = requests.get(
        f"{base_url}/deployments",
        params={"api-version": api_version},
        headers=headers,
        timeout=30,
    )
    deployments_resp.raise_for_status()
    deployments_data = deployments_resp.json()["data"]

    chat_completion_models = {
        m["id"] for m in models_data if m.get("capabilities", {}).get("chat_completion")
    }
    chosen_deployments = [
        d["id"] for d in deployments_data if d.get("model") in chat_completion_models
    ]
    return deployments_data, chosen_deployments


def bootstrap(settings: LLMSettings) -> ModelCatalog:
    templates: Dict[str, BaseLanguageModel] = {}

    print("Bootstrapping Azure OpenAI catalog with settings:", settings)

    # Extract secret values for use
    api_key = (
        settings.AZURE_OPENAI_API_KEY.get_secret_value()
        if settings.AZURE_OPENAI_API_KEY
        else ""
    )

    if api_key:
        try:
            _, deployments = _get_azure_openai_deployments(
                endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=api_key,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )
            for dep in deployments:
                key = AZURE_OPENAI_PREFIX + dep
                templates[key] = AzureChatOpenAI(
                    azure_deployment=dep,
                    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                    api_version=settings.AZURE_OPENAI_API_VERSION,
                    openai_api_key=api_key,
                )
        except Exception as exc:
            logger.warning("Azure discovery failed: %s", exc, exc_info=False)

    if templates:
        logger.info("Available Azure models: %s", ", ".join(sorted(templates)))
        AzureModel = Enum("AzureModel", {name: name for name in templates})
    else:
        logger.warning("No Azure models discovered.")
        AzureModel = Enum("AzureModel", {})

    return ModelCatalog(templates=MappingProxyType(templates), enum=AzureModel)
