import configparser
from pydantic import BaseSettings, Field, SecretStr, root_validator
from .schemas import ExerciseType


class ModuleConfig(BaseSettings):
    """Static module config loaded from module.conf."""

    name: str
    type: ExerciseType
    port: int

    @classmethod
    def from_conf(cls, path: str = "module.conf") -> "ModuleConfig":
        config = configparser.ConfigParser()
        read = config.read(path)
        if not read or "module" not in config:
            raise FileNotFoundError(f"Could not find [module] section in {path}")
        return cls(**config["module"])


class LLMSettings(BaseSettings):
    """Central LLM settings — single source of truth for all model loaders."""

    AZURE_OPENAI_API_KEY: SecretStr = Field("", env="AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT: str = Field("", env="AZURE_OPENAI_API_BASE")
    AZURE_OPENAI_API_VERSION: str = Field(
        "2023-03-15-preview", env="AZURE_OPENAI_API_VERSION"
    )

    # OpenAI
    OPENAI_API_KEY: SecretStr = Field("", env="OPENAI_API_KEY")
    OPENAI_BASE_URL: str = Field("https://api.openai.com/v1", env="OPENAI_BASE_URL")

    # Ollama
    OLLAMA_HOST: str = Field("http://localhost:11434", env="OLLAMA_HOST")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


class Settings(BaseSettings):
    """
    Unified application settings, loaded from environment variables and .env file.
    Keep LLM settings centralized under `llm`.
    """

    PRODUCTION: bool = Field(False, env="PRODUCTION")
    SECRET: SecretStr = Field("development-secret", env="SECRET")
    DATABASE_URL: str = Field("sqlite:///../data/data.sqlite", env="DATABASE_URL")

    # Static module config from module.conf
    module: ModuleConfig = Field(default_factory=ModuleConfig.from_conf)

    # Centralized LLM settings (single source of truth)
    llm: LLMSettings = Field(default_factory=LLMSettings)

    @root_validator
    def _require_secret_in_prod(cls, values):
        """Ensure a strong SECRET is set when running in production."""
        if values.get("PRODUCTION"):
            secret = values.get("SECRET")
            if (
                not isinstance(secret, SecretStr)
                or not secret.get_secret_value()
                or secret.get_secret_value() == "development-secret"
            ):
                raise ValueError(
                    "SECRET must be set to a strong value when PRODUCTION=true"
                )
        return values

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Allow nested settings via env like: LLM__OPENAI_API_KEY=...
        env_nested_delimiter = "__"
