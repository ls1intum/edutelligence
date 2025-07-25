from typing import List
from app.models.model_provider import ModelProvider
from app.models.openai import openai_provider
from app.models.azure_openai import azure_openai_provider
from app.models.ollama import ollama_provider
from app.models.fake import fake_provider

model_providers: List[ModelProvider] = [
    openai_provider,
    azure_openai_provider,
    ollama_provider,
    fake_provider,
]


def get_model(model_name: str):
    """
    Loads and returns the chat model based on the given model_name.

    The model_name should be in the format "provider:model", where:
      - provider: Identifier for the model provider (e.g., "openai", "azure_openai", etc.)
      - model: The specific model name within that provider

    Raises:
        EnvironmentError: If model_name is empty or the provider is not found.
        ValueError: If model_name is not in the correct format.
    """
    if not model_name:
        raise ValueError("model_name is not set")

    try:
        provider_name, actual_model_name = model_name.split(":", 1)
    except ValueError:
        raise ValueError("model_name must be in the format 'provider:model'")

    for provider in model_providers:
        if provider.get_name() == provider_name:
            break
    else:
        model_provider_names = [provider.get_name() for provider in model_providers]
        raise EnvironmentError(
            f"Model provider '{provider_name}' not found in {model_provider_names}"
        )

    provider.validate_provider()
    provider.validate_model_name(actual_model_name)

    ChatModel = provider.get_model(actual_model_name)
    return ChatModel
