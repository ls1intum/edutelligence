import nltk
import tiktoken
from fastapi import FastAPI
from athena.app import run_app
from athena.database import create_tables
from .container import AppContainer
from . import endpoints


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application and container."""
    container = AppContainer()

    # Load settings from environment/files
    settings = container.core.settings()

    # Wire container to endpoint modules
    container.wire(modules=[endpoints])

    # Create FastAPI app
    # We can use FastAPI's lifespan here if needed, but for simple setup,
    # doing it here is also fine.
    app = FastAPI()
    app.container = container
    app.include_router(endpoints.router)

    # One-time setup tasks
    # Pre-download required data
    nltk.download("punkt_tab")
    tiktoken.get_encoding("cl100k_base")

    # Create database tables on startup
    db_engine = container.core.db_engine()
    create_tables(db_engine, settings.module.type)

    return app


# Application instance created by our factory
app = create_app()


if __name__ == "__main__":
    # The run_app function needs the settings from the container.
    # The container is attached to the app object.
    main_settings = app.container.core.settings()
    run_app(app, settings=main_settings)
