import os
import secrets
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

    @field_validator("MODEL_NAME", mode="before")
    @classmethod
    def override_model_name(cls, value):
        if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
            return "fake:model"
        return value

    @field_validator("API_KEY", mode="before")
    @classmethod
    def generate_api_key_if_empty(cls, value):
        if not value:
            token = secrets.token_hex(32)
            logger.warning(f"API key not set, generating a random one: {token}")
            return token
        return value


settings = Settings()

if settings.DISABLE_AUTH:
    logger.warning(
        "API authentication is disabled. This is not recommended for production."
    )
