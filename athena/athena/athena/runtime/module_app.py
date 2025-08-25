from __future__ import annotations
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Protocol, Type, Any

import os
import yaml
from fastapi import FastAPI
from sqlalchemy import create_engine

from athena.app import create_app as create_athena_app
from athena.settings import Settings
from athena.database import create_tables
from athena.schemas.exercise_type import ExerciseType
from llm_core.loaders.model_loaders.azure_loader import bootstrap as azure_bootstrap
from llm_core.loaders.model_loaders.openai_loader import bootstrap as openai_bootstrap
from llm_core.loaders.model_loaders.ollama_loader import bootstrap as ollama_bootstrap
from llm_core.loaders.llm_config_loader import get_llm_config
from llm_core.models.llm_config import LLMConfig


class ModulePlugin(Protocol):
    """What a module must provide to be bootstrapped generically."""

    exercise_type: ExerciseType  # modeling | text | programming
    config_cls: Type  # Pydantic configuration model for this module

    def build_default_config(self, llm: LLMConfig) -> Any:
        """Build the default configuration for this module using the LLM config."""
        ...

    def register_routes(self, app: FastAPI) -> None:
        """Import endpoints to register routes on the app."""
        ...

    def warm_start(self) -> None:
        """Optional: heavyweight init (nltk/tiktoken, etc.)."""
        return None


def _build_factories(azure_catalog, openai_catalog, ollama_catalog):
    from llm_core.models.providers.openai_model_config import OpenAIModelConfig
    from llm_core.models.providers.azure_model_config import AzureModelConfig
    from llm_core.models.providers.ollama_model_config import OllamaModelConfig

    class _Factories:
        def openai_model_config(self, **kw):
            return OpenAIModelConfig(catalog=openai_catalog, **kw)

        def azure_model_config(self, **kw):
            return AzureModelConfig(catalog=azure_catalog, **kw)

        def ollama_model_config(self, **kw):
            return OllamaModelConfig(catalog=ollama_catalog, **kw)

    return _Factories()


def _load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        # No llm_config.yml is acceptable; caller can handle missing models.
        return {}


def _discover_llms(settings: Settings):
    # Centralized discovery via llm_core loaders
    # (works even if creds are missing; returns empty catalogs)
    s = settings.llm if hasattr(settings, "llm") else settings
    return (
        azure_bootstrap(s),  # azure_catalog
        openai_bootstrap(s),  # openai_catalog
        ollama_bootstrap(s),  # ollama_catalog
    )


def _ensure_tables(settings: Settings, exercise_type: ExerciseType) -> None:
    engine = create_engine(settings.DATABASE_URL)
    create_tables(engine=engine, exercise_type=exercise_type.value)


@asynccontextmanager
async def _lifespan(app: FastAPI, plugin: ModulePlugin):
    # 1) settings
    settings = getattr(app.state, "settings", None)
    if settings is None:
        settings = Settings(
            PRODUCTION=os.getenv("PRODUCTION", "False").lower() in ("true", "1", "yes"),
            SECRET=os.getenv("SECRET", "development-secret"),
        )
        app.state.settings = settings

    # 2) LLM discovery
    azure_catalog, openai_catalog, ollama_catalog = _discover_llms(settings)

    app.state.ctx = SimpleNamespace(
        azure_catalog=azure_catalog,
        openai_catalog=openai_catalog,
        ollama_catalog=ollama_catalog,
    )

    # 3) llm_config.yml -> LLMConfig; then build module default config
    raw_llm = _load_yaml("llm_config.yml")
    factories = _build_factories(azure_catalog, openai_catalog, ollama_catalog)
    llm_config = get_llm_config(raw_config=raw_llm, factories=factories)

    default_cfg = plugin.build_default_config(llm_config)  # module's Pydantic config
    app.state.module_config = default_cfg

    # 4) DB tables for this module's exercise type
    from athena.database import init_engine
    init_engine(settings.DATABASE_URL)
    _ensure_tables(settings, plugin.exercise_type)

    # 5) Optional warm start
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, plugin.warm_start)
    except Exception:
        # Keep startup resilient; logging is handled by athena.logger
        pass

    yield


def create_module_app(plugin: ModulePlugin) -> FastAPI:
    app = create_athena_app(lambda a=..., p=plugin: _lifespan(a, p))
    plugin.register_routes(app)  # imports endpoints so routes get registered
    return app
