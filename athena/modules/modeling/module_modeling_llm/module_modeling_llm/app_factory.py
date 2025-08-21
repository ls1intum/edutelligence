from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import yaml
from fastapi import FastAPI

from athena.app import create_app as create_athena_app
from athena.settings import Settings
from athena.module_config import get_module_config
from athena.database import create_tables
from athena.schemas.exercise_type import ExerciseType

# LLM discovery + config materialization
from llm_core.loaders.model_loaders.azure_loader import bootstrap as azure_bootstrap
from llm_core.loaders.model_loaders.openai_loader import bootstrap as openai_bootstrap
from llm_core.loaders.model_loaders.ollama_loader import bootstrap as ollama_bootstrap
from llm_core.loaders.llm_config_loader import get_llm_config
from llm_core.utils.model_factory import ModelFactories

from module_modeling_llm.config import Configuration, BasicApproachConfig


def _build_factories(azure_catalog, openai_catalog, ollama_catalog) -> ModelFactories:
    class _Factories:
        def openai_model_config(self, **kwargs):
            from llm_core.models.providers.openai_model_config import OpenAIModelConfig

            return OpenAIModelConfig(catalog=openai_catalog, **kwargs)

        def azure_model_config(self, **kwargs):
            from llm_core.models.providers.azure_model_config import AzureModelConfig

            return AzureModelConfig(catalog=azure_catalog, **kwargs)

        def ollama_model_config(self, **kwargs):
            from llm_core.models.providers.ollama_model_config import OllamaModelConfig

            return OllamaModelConfig(catalog=ollama_catalog, **kwargs)

    return _Factories()  # type: ignore


def _warm_start():
    import nltk, tiktoken

    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt")
    tiktoken.get_encoding("cl100k_base")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) settings - reuse if already set by run_app, otherwise create
    settings = getattr(app.state, "settings", None)
    if settings is None:
        import os

        settings = Settings(
            PRODUCTION=os.getenv("PRODUCTION", "False").lower() in ("true", "1", "yes"),
            SECRET=os.getenv("SECRET", "development-secret"),
        )
        app.state.settings = settings

    # 2) discover LLM catalogs (optional if credentials missing)
    azure_catalog = azure_bootstrap(settings.llm if hasattr(settings, "llm") else settings)  # type: ignore
    openai_catalog = openai_bootstrap(settings.llm if hasattr(settings, "llm") else settings)  # type: ignore
    ollama_catalog = ollama_bootstrap(settings.llm if hasattr(settings, "llm") else settings)  # type: ignore

    app.state.ctx = SimpleNamespace(
        azure_catalog=azure_catalog,
        openai_catalog=openai_catalog,
        ollama_catalog=ollama_catalog,
    )

    # 3) load llm_config.yml and bake a default module Configuration
    with open("llm_config.yml", "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    factories = _build_factories(azure_catalog, openai_catalog, ollama_catalog)
    llm_config = get_llm_config(raw_config=raw, factories=factories)

    # build the module's default Configuration using discovered model configs
    approach = BasicApproachConfig(
        generate_feedback=llm_config.models.base_model_config,
        filter_feedback=llm_config.models.mini_model_config
        or llm_config.models.base_model_config,
        review_feedback=llm_config.models.fast_reasoning_model_config
        or llm_config.models.base_model_config,
        generate_grading_instructions=llm_config.models.long_reasoning_model_config
        or llm_config.models.base_model_config,
    )
    app.state.module_config = Configuration(approach=approach)

    # 4) ensure tables exist for this module type
    module_cfg = get_module_config()
    from sqlalchemy import create_engine

    engine = create_engine(settings.DATABASE_URL)
    create_tables(engine=engine, exercise_type=module_cfg.type.value)

    # 5) warm start
    import asyncio

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _warm_start)

    yield


def create_app() -> FastAPI:
    app = create_athena_app(lifespan)
    from .endpoints import suggest_feedback  # Import to register the endpoint

    return app
