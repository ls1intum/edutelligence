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
     - embeddings: List of embedding model identifiers.
     - learning_extractor: Model identifier for the learning extractor.
     - learning_deduplicator: Model identifier for the learning deduplicator.
     - memory_creator: Model identifier for the memory creator.
     - sleep_tool_llm: Model identifier for the sleep tool LLM.
     - sleep_json_llm: Model identifier for the sleep JSON LLM.
    """

    embeddings: list[str] = Field(default_factory=list)
    learning_extractor: str = Field()
    learning_deduplicator: str = Field()
    memory_creator: str = Field()
    sleep_tool_llm: str = Field()
    sleep_json_llm: str = Field()


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


class Settings(BaseModel):
    """Settings represents application configuration settings loaded from a YAML file."""

    api_keys: list[APIKeyConfig]
    env_vars: dict[str, str]
    weaviate: WeaviateSettings
    memiris: MemirisSettings
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    local_llm_enabled: bool = Field(default=True)
    llm_configuration: dict[str, LlmVariantConfiguration] = Field(default_factory=dict)

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
