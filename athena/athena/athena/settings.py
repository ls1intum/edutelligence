import configparser
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from .schemas import ExerciseType
from pydantic import model_validator


class ModuleConfig(BaseSettings):
    """Static module config loaded from module.conf"""

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
    """Central LLM settings - single source of truth for all model loaders"""

    AZURE_OPENAI_API_KEY: SecretStr = Field(
        validation_alias="AZURE_OPENAI_API_KEY"
    )
    AZURE_OPENAI_ENDPOINT: str = Field(
        validation_alias="AZURE_OPENAI_ENDPOINT"
    )
    AZURE_OPENAI_API_VERSION: str = Field(
        default="2023-03-15-preview",
        validation_alias="AZURE_OPENAI_API_VERSION",
    )

    # OpenAI
    OPENAI_API_KEY: SecretStr = Field(
        validation_alias="OPENAI_API_KEY",
    )
    OPENAI_BASE_URL: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
    )

    # Ollama
    OLLAMA_HOST: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_HOST",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

class Settings(BaseSettings):
    """
    Unified application settings, loaded from environment variables and .env file
    """

    PRODUCTION: bool = Field(False, validation_alias="PRODUCTION")
    SECRET: SecretStr = Field(
        default=SecretStr("development-secret"),
        validation_alias="SECRET",
    )
    DATABASE_URL: str = Field(
        default="sqlite:///../data/data.sqlite",
        validation_alias="DATABASE_URL",
    )

    # Static module config from module.conf
    module: ModuleConfig = Field(default_factory=ModuleConfig.from_conf)

    # Centralized LLM settings (single source of truth)
    llm: LLMSettings = Field(default_factory=LLMSettings)

    @model_validator(mode="after")
    def _require_secret_in_prod(self):
        """Ensure a strong SECRET is set when running in production."""
        if self.PRODUCTION:
            # SECRET is a SecretStr; pull the actual value
            secret_value = (
                self.SECRET.get_secret_value()
                if isinstance(self.SECRET, SecretStr) else str(self.SECRET or "")
            )
            if not secret_value or secret_value == "development-secret":
                raise ValueError(
                    "SECRET must be set to a strong value when PRODUCTION=true"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )