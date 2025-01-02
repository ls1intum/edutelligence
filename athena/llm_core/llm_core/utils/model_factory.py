
from typing import Optional
from llm_core.models.openai_model_config import OpenAIModelConfig

def find_provider_for_model(model_name: str) -> Optional[str]:
    """
    Determine which provider a model_name belongs to based on its prefix or a naming pattern.
    """
    model_name_lower = model_name.lower()

    if model_name_lower.startswith("openai_"):
        return "openai"
    elif model_name_lower.startswith("azure_openai_"):
        return "azure_openai"
    elif model_name_lower.startswith("replicate_"):
        return "replicate"
    else:
        return None

def create_config_for_model(model_name: str) -> OpenAIModelConfig:  # or Union[OpenAIModelConfig, AzureOpenAIModelConfig, ...]
    """
    Create the appropriate ModelConfig subclass instance (OpenAI, Azure, etc.) 
    depending on the provider indicated by `model_name`.
    """
    provider = find_provider_for_model(model_name)
    if provider == "openai":
        return OpenAIModelConfig(model_name=model_name)
    elif provider == "azure_openai":
        return OpenAIModelConfig(model_name=model_name)
    elif provider == "replicate":
        raise NotImplementedError("Replicate support is not implemented yet.")
    else:
        raise ValueError(f"Unknown provider for model name '{model_name}'")