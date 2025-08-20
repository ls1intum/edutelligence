# llm_core/llm_core/container.py
from dependency_injector import containers, providers
from athena.settings import Settings
from .catalog import ModelCatalog
from .loaders.model_loaders import azure_loader, openai_loader, ollama_loader
from .models.providers.openai_model_config import OpenAIModelConfig
from .models.providers.azure_model_config import AzureModelConfig
from .models.providers.ollama_model_config import OllamaModelConfig
from .loaders.llm_config_loader import get_llm_config
from types import SimpleNamespace


def load_raw_config(path):
    c = providers.Configuration()
    c.from_yaml(path)
    return c()


class LLMContainer(containers.DeclarativeContainer):
    """Container for LLM-related services with clean bootstrap design."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "llm_core.loaders.model_loaders.azure_loader",
            "llm_core.loaders.model_loaders.openai_loader",
            "llm_core.loaders.model_loaders.ollama_loader",
            "llm_core.models.providers.openai_model_config",
            "llm_core.models.providers.azure_model_config",
            "llm_core.models.providers.ollama_model_config",
        ]
    )

    # The module passes a path for its llm_config.yml (overridden upstream)
    config_path = providers.Configuration()

    # Load raw YAML at runtime by resolving the path first
    raw_llm_config = providers.Factory(load_raw_config, path=config_path)

    # Settings (includes .llm with provider creds)
    settings = providers.Singleton(Settings)

    # LLM catalogs discovered from env/hosts; these are lazy singletons
    azure_catalog = providers.Singleton[ModelCatalog](
        azure_loader.bootstrap,
        settings=providers.Factory(lambda s: s.llm, s=settings),
    )

    openai_catalog = providers.Singleton[ModelCatalog](
        openai_loader.bootstrap,
        settings=providers.Factory(lambda s: s.llm, s=settings),
    )

    ollama_catalog = providers.Singleton[ModelCatalog](
        ollama_loader.bootstrap,
        settings=providers.Factory(lambda s: s.llm, s=settings),
    )

    # Provider-config factories (order matters; define before model_factories)
    openai_model_config = providers.Factory(OpenAIModelConfig)
    azure_model_config = providers.Factory(AzureModelConfig)
    ollama_model_config = providers.Factory(OllamaModelConfig)

    # We pass a simple namespace of factories into get_llm_config (no providers.Self())
    model_factories = providers.Object(
        SimpleNamespace(
            openai_model_config=openai_model_config,
            azure_model_config=azure_model_config,
            ollama_model_config=ollama_model_config,
        )
    )

    # Materialize typed LLMConfig from the raw YAML + factories
    llm_config = providers.Singleton(
        get_llm_config,
        raw_config=raw_llm_config,
        factories=model_factories,
    )

    # Handy projections
    llm_models = providers.Factory(lambda cfg: cfg.models, cfg=llm_config).provided
