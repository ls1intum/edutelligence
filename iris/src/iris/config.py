import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class APIKeyConfig(BaseModel):
    token: str


class WeaviateSettings(BaseModel):
    host: str
    port: int
    grpc_port: int


class MemirisSettings(BaseModel):
    enabled: bool = Field(default=True)
    sleep_enabled: bool = Field(default=True)


class Settings(BaseModel):
    """Settings represents application configuration settings loaded from a YAML file."""

    api_keys: list[APIKeyConfig]
    env_vars: dict[str, str]
    weaviate: WeaviateSettings
    memiris: MemirisSettings

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
