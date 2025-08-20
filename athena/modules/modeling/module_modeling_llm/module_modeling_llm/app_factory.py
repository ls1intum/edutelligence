from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
from fastapi import FastAPI
from athena.settings import Settings
from athena.database import create_tables
from athena.app import app as base_app
from athena import module_health
from llm_core.loaders.model_loaders import azure_loader, openai_loader, ollama_loader
from llm_core.utils.model_factory import ModelFactories as ModelFactoriesProtocol
from llm_core.loaders.llm_config_loader import get_llm_config
from types import SimpleNamespace
from llm_core.models.providers.openai_model_config import OpenAIModelConfig
from llm_core.models.providers.azure_model_config import AzureModelConfig
from llm_core.models.providers.ollama_model_config import OllamaModelConfig
from sqlalchemy import create_engine
from module_modeling_llm.core.context import AppContext
from module_modeling_llm.config import Configuration, BasicApproachConfig


def load_raw_config(path):
    import yaml

    with open(path, "r") as f:
        return yaml.safe_load(f)


def _warm_start():
    import nltk, tiktoken

    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt")
    tiktoken.get_encoding("cl100k_base")


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        print("Module 'module_modeling_llm' is starting up...")

        # Use the settings from environment automatically via pydantic
        import os

        settings = Settings(
            PRODUCTION=os.getenv("PRODUCTION", "False").lower() in ("true", "1", "yes"),
            SECRET=os.getenv("SECRET", "development-secret"),
        )

        # Bootstrap catalogs
        azure_catalog = azure_loader.bootstrap(settings=settings.llm)
        openai_catalog = openai_loader.bootstrap(settings=settings.llm)
        ollama_catalog = ollama_loader.bootstrap(settings=settings.llm)

        # Factories with catalogs
        class ModelFactories(ModelFactoriesProtocol):
            def openai_model_config(self, **kw):
                return OpenAIModelConfig(catalog=openai_catalog, **kw)

            def azure_model_config(self, **kw):
                return AzureModelConfig(catalog=azure_catalog, **kw)

            def ollama_model_config(self, **kw):
                return OllamaModelConfig(catalog=ollama_catalog, **kw)

        factories = ModelFactories()

        # Load llm_config.yml
        config_path = Path(__file__).resolve().parent.parent / "llm_config.yml"
        raw_config = load_raw_config(config_path)
        llm_config = get_llm_config(raw_config, factories)

        # Default config using llm_config
        default_config = Configuration(
            approach=BasicApproachConfig(
                generate_feedback=llm_config.models.base_model_config,
                filter_feedback=llm_config.models.base_model_config,
                review_feedback=llm_config.models.base_model_config,
                generate_grading_instructions=llm_config.models.base_model_config,
            )
        )

        # LLM factory with fast fail on unknown models
        all_templates = {
            **azure_catalog.templates,
            **openai_catalog.templates,
            **ollama_catalog.templates,
        }

        def llm_factory(name: str):
            if name not in all_templates:
                from fastapi import HTTPException

                raise HTTPException(status_code=400, detail=f"Unknown model '{name}'")
            return all_templates[name]

        ctx = AppContext(
            azure_catalog=azure_catalog,
            openai_catalog=openai_catalog,
            ollama_catalog=ollama_catalog,
            default_config=default_config,
            llm_factory=llm_factory,
        )
        app.state.ctx = ctx

        # DB
        db_engine = create_engine(settings.DATABASE_URL)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, create_tables, db_engine, settings.module.type.name
        )
        await loop.run_in_executor(None, _warm_start)

        try:
            yield
        finally:
            print("Module 'module_modeling_llm' is shutting down.")

    from athena.app import create_app as athena_create_app

    app = athena_create_app(lifespan)
    from .endpoints import suggest_feedback  # Import to register the endpoint

    return app
