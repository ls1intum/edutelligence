import configparser
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


class Settings(BaseSettings):
    """
    Unified application settings, loaded from environment variables and .env file.
    """

    PRODUCTION: bool = Field(False)
    SECRET: str
    DATABASE_URL: str = "sqlite:///../data/data.sqlite"

    # LLM Credentials
    OPENAI_API_KEY: str | None = None
    AZURE_OPENAI_API_KEY: str | None = None
    AZURE_OPENAI_ENDPOINT: str | None = None
    OPENAI_API_VERSION: str | None = None
    OLLAMA_ENDPOINT: str | None = None

    # Module-specific static config
    module: ModuleConfig = Field(default_factory=ModuleConfig.from_conf)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
