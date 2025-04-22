import os
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hyperion.logger import logger

load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # API Security
    API_KEY: str = ""
    DISABLE_AUTH: bool = False

    # Playground Security
    PLAYGROUND_USERNAME: str = "playground"
    PLAYGROUND_PASSWORD: str = ""

    # Model to use prefixed by provider, i.e. "openai:gpt-4o"
    MODEL_NAME: str = ""

    # Non-Azure OpenAI
    OPENAI_API_KEY: str = ""

    # Azure OpenAI
    OPENAI_API_VERSION: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""

    # Ollama settings
    OLLAMA_BASIC_AUTH_USERNAME: str = ""
    OLLAMA_BASIC_AUTH_PASSWORD: str = ""
    OLLAMA_HOST: str = ""

    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = ""

    # Add a flag for OpenAPI generation mode
    IS_GENERATING_OPENAPI: bool = False

    @property
    def langfuse_enabled(self):
        return bool(
            self.LANGFUSE_PUBLIC_KEY
            and self.LANGFUSE_SECRET_KEY
            and self.LANGFUSE_HOST
            and not self.IS_GENERATING_OPENAPI
        )

    @field_validator("MODEL_NAME", mode="before")
    @classmethod
    def override_model_name(cls, value):
        if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
            return "fake:model"
        return value


settings = Settings()

if settings.DISABLE_AUTH:
    logger.warning(
        "API authentication is disabled. This is not recommended for production."
    )
