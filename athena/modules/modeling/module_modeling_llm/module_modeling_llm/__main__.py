from contextlib import contextmanager
import nltk
import tiktoken
from fastapi import FastAPI

from athena.app import create_app, run_app
from athena.database import create_tables
from .container import AppContainer
from . import endpoints


container = AppContainer()


# 2. Define the module-specific startup and shutdown logic using FastAPI's modern 'lifespan' context manager.
#    This is the "hook" into the athena framework.
@contextmanager
def lifespan(app: FastAPI):
    # --- Code to run on startup ---
    print("Module 'module_modeling_llm' is starting up...")

    # Wire the DI container to the endpoints that need it.
    app.container = container
    container.wire(modules=[endpoints])

    # Perform one-time setup tasks for this module.
    nltk.download("punkt_tab")
    tiktoken.get_encoding("cl100k_base")

    # Get database engine from the container and create tables.
    settings = container.core.settings()
    db_engine = container.core.db_engine()
    create_tables(db_engine, settings.module.type)

    print("Startup complete.")

    yield

    print("Module 'module_modeling_llm' is shutting down.")
