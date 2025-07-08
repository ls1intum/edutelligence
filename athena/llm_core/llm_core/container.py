from dependency_injector import containers, providers
from .loaders.llm_config_loader import get_llm_config
from .models.llm_config import LLMConfigModel


class LLMContainer(containers.DeclarativeContainer):
    """Container for LLM-related services."""

    # Path to llm_config.yml will be provided by the application container
    config_path = providers.Configuration()

    llm_config = providers.Singleton(
        get_llm_config,
        path=config_path,
    )

    llm_models = providers.Factory(
        lambda config: config.models,
        config=llm_config,
    ).provided

    base_model_config = providers.Factory(
        lambda models: models.base_model_config,
        models=llm_models,
    ).provided
