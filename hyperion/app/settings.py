import os
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.logger import logger

load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # API Security
    API_KEY: str = ""
    DISABLE_AUTH: bool = False

    # Model to use prefixed by provider, i.e. "openai:o4-mini"
    MODEL_NAME: str = ""

    # OpenRouter
    OPENROUTER_API_KEY: str = ""

    # OpenWebUI
    OPENWEBUI_API_KEY: str = ""
    OPENWEBUI_BASE_URL: str = ""

    # Add a flag for OpenAPI generation mode
    IS_GENERATING_OPENAPI: bool = False


settings = Settings()

if settings.DISABLE_AUTH:
    logger.warning(
        "API authentication is disabled. This is not recommended for production."
    )
