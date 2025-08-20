import configparser
import os
from dataclasses import dataclass
from pydantic import BaseSettings, Field
from .schemas import ExerciseType


class ModuleConfig(BaseSettings):
    """Config from module.conf."""

    name: str
    type: ExerciseType
    port: int

    @classmethod
    def from_conf(cls, path: str = "module.conf"):
        config = configparser.ConfigParser()
        config.read(path)
        if "module" not in config:
            raise FileNotFoundError(f"Could not find [module] section in {path}")
        return cls(**config["module"])


@dataclass(frozen=True)
class LLMSettings:
    """Central LLM settings — single source of truth for all model loaders."""

    # Azure OpenAI
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_VERSION: str = "2023-03-15-preview"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"  # optional proxy/gateway

    # Ollama
    OLLAMA_HOST: str = "http://localhost:11434"

    @classmethod
    def from_env(cls) -> "LLMSettings":
        """Create settings from environment variables (no I/O at import)."""
        return cls(
            AZURE_OPENAI_API_KEY=os.getenv("AZURE_OPENAI_API_KEY", ""),
            AZURE_OPENAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            AZURE_OPENAI_API_VERSION=os.getenv(
                "AZURE_OPENAI_API_VERSION", "2023-03-15-preview"
            ),
            OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
            OPENAI_BASE_URL=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            OLLAMA_HOST=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        )


class Settings(BaseSettings):
    """
    Unified application settings, loaded from environment variables and .env file.
    Keep LLM settings centralized under `llm`.
    """

    PRODUCTION: bool = Field(False)
    SECRET: str
    DATABASE_URL: str = "sqlite:///../data/data.sqlite"

    # Static module config from module.conf
    module: ModuleConfig = Field(default_factory=ModuleConfig.from_conf)

    # Centralized LLM settings (single source of truth)
    llm: LLMSettings = Field(default_factory=LLMSettings.from_env)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
