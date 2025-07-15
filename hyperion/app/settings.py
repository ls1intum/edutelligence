import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # gRPC server settings
    GRPC_HOST: str = "0.0.0.0"
    GRPC_PORT: int = 50051
    GRPC_MAX_WORKERS: int = 10

    # TLS settings for production gRPC
    TLS_ENABLED: bool = False
    TLS_CERT_PATH: str = ""
    TLS_KEY_PATH: str = ""
    TLS_CA_PATH: str = ""  # For client certificate verification

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

    @property
    def GRPC_ADDRESS(self) -> str:
        """Centralized gRPC address computation."""
        return f"{self.GRPC_HOST}:{self.GRPC_PORT}"

    @property
    def langfuse_enabled(self):
        return bool(
            self.LANGFUSE_PUBLIC_KEY
            and self.LANGFUSE_SECRET_KEY
            and self.LANGFUSE_HOST
            and not self.IS_GENERATING_OPENAPI
        )

    @field_validator("TLS_CERT_PATH", mode="after")
    @classmethod
    def validate_cert_path(cls, value, info):
        """Ensure TLS cert path exists when TLS is enabled."""
        if info.data.get("TLS_ENABLED") and value and not Path(value).is_file():
            raise ValueError(
                f"TLS_CERT_PATH must point to a valid file when TLS is enabled: {value}"
            )
        return value

    @field_validator("TLS_KEY_PATH", mode="after")
    @classmethod
    def validate_key_path(cls, value, info):
        """Ensure TLS key path exists when TLS is enabled."""
        if info.data.get("TLS_ENABLED") and value and not Path(value).is_file():
            raise ValueError(
                f"TLS_KEY_PATH must point to a valid file when TLS is enabled: {value}"
            )
        return value

    @field_validator("TLS_CA_PATH", mode="after")
    @classmethod
    def validate_ca_path(cls, value, info):
        """Ensure TLS CA path exists when specified."""
        if info.data.get("TLS_ENABLED") and value and not Path(value).is_file():
            raise ValueError(
                f"TLS_CA_PATH must point to a valid file when specified: {value}"
            )
        return value

    @field_validator("MODEL_NAME", mode="before")
    @classmethod
    def override_model_name(cls, value):
        if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
            return "fake:model"
        return value


settings = Settings()
