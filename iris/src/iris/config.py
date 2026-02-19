import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class APIKeyConfig(BaseModel):
    token: str


class WeaviateSettings(BaseModel):
    host: str
    port: int
    grpc_port: int


class MemirisSettings(BaseModel):
    enabled: bool = Field(default=True)
    sleep_enabled: bool = Field(default=True)


class LangfuseSettings(BaseModel):
    """Settings for LangFuse observability integration."""

    enabled: bool = Field(default=False)
    public_key: Optional[str] = Field(default=None)
    secret_key: Optional[str] = Field(default=None)
    host: str = Field(default="https://cloud.langfuse.com")

    @model_validator(mode="after")
    def validate_keys_when_enabled(self):
        """Validate that keys are provided when LangFuse is enabled."""
        if self.enabled and (not self.public_key or not self.secret_key):
            raise ValueError(
                "LangFuse public_key and secret_key are required when enabled=True"
            )
        return self


class TranscriptionSettings(BaseModel):
    """Settings for video transcription pipeline.

    Note: Whisper API configuration is loaded from llm_config.yml,
    not from application.yml. Add a whisper entry to llm_config.yml
    with type 'azure_whisper' or 'openai_whisper'.
    """

    enabled: bool = Field(default=False, description="Enable video transcription")
    temp_dir: str = Field(
        default="tmp/transcription",
        description="Directory for temporary video/audio files",
    )
    chunk_duration_seconds: int = Field(
        default=900, description="Audio chunk duration in seconds (default: 15 min)"
    )
    whisper_model: str = Field(
        default="whisper",
        description="Model ID to look up in llm_config.yml",
    )


class Settings(BaseModel):
    """Settings represents application configuration settings loaded from a YAML file."""

    api_keys: list[APIKeyConfig]
    env_vars: dict[str, str]
    weaviate: WeaviateSettings
    memiris: MemirisSettings
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)

    @classmethod
    def get_settings(cls):
        """Get the settings from the configuration file."""
        file_path_env = os.environ.get("APPLICATION_YML_PATH")
        if not file_path_env:
            raise EnvironmentError(
                "APPLICATION_YML_PATH environment variable is not set."
            )

        file_path = Path(file_path_env)
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                settings_file = yaml.safe_load(file)
            return cls.model_validate(settings_file)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Configuration file not found at {file_path}."
            ) from e
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML file at {file_path}.") from e

    def set_env_vars(self):
        """Set environment variables from the settings."""
        for key, value in self.env_vars.items():
            os.environ[key] = value


def load_whisper_config(model: str = "whisper") -> dict:
    """
    Load Whisper configuration from llm_config.yml.

    Args:
        model: The model ID to look up in llm_config.yml.

    Returns:
        Dict containing the Whisper configuration.

    Raises:
        ValueError: If LLM_CONFIG_PATH is not set or model not found.
        FileNotFoundError: If the config file doesn't exist.
    """
    llm_config_path = os.environ.get("LLM_CONFIG_PATH")
    if not llm_config_path:
        raise ValueError("LLM_CONFIG_PATH environment variable is not set.")

    file_path = Path(llm_config_path)
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            llm_configs = yaml.safe_load(file)

        # Find the whisper config by id
        for config in llm_configs:
            if config.get("id") == model:
                return config

        raise ValueError(f"Whisper model '{model}' not found in {file_path}")

    except FileNotFoundError as e:
        raise FileNotFoundError(f"LLM config file not found at {file_path}.") from e
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML file at {file_path}.") from e


settings = Settings.get_settings()
