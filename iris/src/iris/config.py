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

    Note: Whisper API configuration (endpoint, key, deployment) is loaded
    from llm_config.yml, not from application.yml. Add a whisper entry to
    llm_config.yml with type 'azure_whisper' or 'openai_whisper' and set
    whisper_model to its id.

    FFmpeg timeout fields (download_timeout_seconds, extract_audio_timeout_seconds)
    guard against stalled network streams or corrupt files blocking a worker indefinitely.
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
    whisper_max_workers: int = Field(
        default=2,
        description="Max parallel Whisper API requests per transcription job",
    )
    whisper_request_timeout_seconds: int = Field(
        default=300,
        description=(
            "Timeout in seconds for a single Whisper API request. "
            "Should be at least chunk_duration_seconds / 3 to account for processing time."
        ),
    )
    whisper_max_retries: int = Field(
        default=6,
        description="Max retry attempts per chunk on transient failures",
    )
    max_concurrent_jobs: int = Field(
        default=2,
        description="Max concurrent video transcription jobs (semaphore slots)",
    )
    download_timeout_seconds: int = Field(
        default=3600,
        description="Timeout in seconds for video download via FFmpeg (default: 1 hour)",
    )
    extract_audio_timeout_seconds: int = Field(
        default=600,
        description="Timeout in seconds for audio extraction via FFmpeg (default: 10 minutes)",
    )
    no_speech_filter_threshold: float = Field(
        default=0.8,
        description=(
            "Whisper no_speech_prob threshold for filtering non-speech segments (0.0–1.0). "
            "Segments whose no_speech_prob exceeds this value are discarded. "
            "Higher values are more conservative (keep more segments). "
            "Default 0.8 is calibrated for noisy lecture halls — lower to 0.6 for quiet studio recordings. "
            "Set to 1.0 to disable filtering entirely."
        ),
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


settings = Settings.get_settings()
