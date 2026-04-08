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


class MemirisLlmConfiguration(BaseModel):
    """
    Configuration for the LLMs used by Memiris.
     - embeddings: List of embedding model identifiers (same for local and cloud).
     - learning_extractor: Model identifier(s) for the learning extractor.
        Can be a string or dict with 'local' and 'cloud' keys.
     - learning_deduplicator: Model identifier(s) for the learning deduplicator.
        Can be a string or dict with 'local' and 'cloud' keys.
     - memory_creator: Model identifier(s) for the memory creator.
        Can be a string or dict with 'local' and 'cloud' keys.
     - sleep_tool_llm: Model identifier(s) for the sleep tool LLM.
        Can be a string or dict with 'local' and 'cloud' keys.
     - sleep_json_llm: Model identifier(s) for the sleep JSON LLM.
        Can be a string or dict with 'local' and 'cloud' keys.
    """

    embeddings: list[str] = Field(default_factory=list)
    learning_extractor: str | dict[str, str] = Field()
    learning_deduplicator: str | dict[str, str] = Field()
    memory_creator: str | dict[str, str] = Field()
    sleep_tool_llm: str | dict[str, str] = Field()
    sleep_json_llm: str | dict[str, str] = Field()


class MemirisSettings(BaseModel):
    """
    Settings for Memiris configuration.
     - enabled: Whether Memiris is enabled or not.
     - sleep_enabled: Whether the sleep functionality of Memiris is enabled or not.
     - llm_configuration: The configuration for the LLMs used by Memiris. Required if Memiris is enabled.
    """

    enabled: bool = Field(default=True)
    sleep_enabled: bool = Field(default=True)
    llm_configuration: Optional[MemirisLlmConfiguration] = Field(default=None)

    @model_validator(mode="after")
    def validate_llm_configuration_when_enabled(self):
        """Validate that LLM configuration is provided when Memiris is enabled."""
        if self.enabled and not self.llm_configuration:
            raise ValueError(
                "Memiris llm_configuration is required when memiris.enabled=True"
            )
        return self


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


LlmRoleConfiguration = dict[
    str, dict[str, str] | str
]  # role -> {local/cloud -> model_id} or role -> model_id (for roles like embedding/reranker)
LlmVariantConfiguration = dict[str, LlmRoleConfiguration]  # variant_id -> role config


class TranscriptionSettings(BaseModel):
    """Settings for video transcription pipeline.

    Whisper API configuration (endpoint, key, deployment) is loaded from
    llm_config.yml, not here.  Add an entry with type 'azure_whisper' or
    'openai_whisper' to llm_config.yml and set whisper_model to its id.
    """

    enabled: bool = Field(default=False, description="Enable video transcription")
    temp_dir: str = Field(
        default="/tmp/nebula-transcription",  # nosec B108
        description="Directory for temporary video/audio files",
    )
    chunk_duration_seconds: int = Field(
        default=900, description="Audio chunk duration in seconds (default: 15 min)"
    )
    whisper_model: str = Field(
        default="whisper",
        description="Model ID to look up in llm_config.yml",
    )
    whisper_max_workers: int = Field(
        default=2,
        description="Max parallel Whisper API requests per transcription job",
    )
    whisper_request_timeout_seconds: int = Field(
        default=300,
        description="Timeout in seconds for a single Whisper API request",
    )
    whisper_max_retries: int = Field(
        default=6,
        description="Max retry attempts per chunk on transient failures",
    )
    download_timeout_seconds: int = Field(
        default=3600,
        description="Timeout for video download via FFmpeg (default: 1 hour)",
    )
    extract_audio_timeout_seconds: int = Field(
        default=600,
        description="Timeout for audio extraction via FFmpeg (default: 10 min)",
    )
    no_speech_filter_threshold: float = Field(
        default=0.8,
        description=(
            "Whisper no_speech_prob threshold (0.0-1.0). Segments above this "
            "are discarded. Use 0.8 for noisy lecture halls, 0.6 for studios, "
            "1.0 to disable."
        ),
    )


class Settings(BaseModel):
    """Settings represents application configuration settings loaded from a YAML file."""

    api_keys: list[APIKeyConfig]
    env_vars: dict[str, str]
    weaviate: WeaviateSettings
    memiris: MemirisSettings
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    local_llm_enabled: bool = Field(default=True)
    llm_configuration: dict[str, LlmVariantConfiguration] = Field(default_factory=dict)
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


settings = Settings.get_settings()
