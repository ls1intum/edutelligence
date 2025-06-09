import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class APIKeyConfig(BaseModel):
    token: str


class WeaviateSettings(BaseModel):
    host: str
    port: int
    grpc_port: int


class Settings(BaseModel):
    api_keys: list[APIKeyConfig]
    weaviate: WeaviateSettings

    @classmethod
    def get_settings(cls):
        """Get the settings from the configuration file."""
        file_path_env = os.environ.get("APPLICATION_YML_PATH")
        if not file_path_env:
            raise OSError("APPLICATION_YML_PATH environment variable is not set.")

        file_path = Path(file_path_env)
        try:
            with open(file_path, encoding="utf-8") as file:
                settings_file = yaml.safe_load(file)
            return cls.model_validate(settings_file)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Configuration file not found at {file_path}."
            ) from e
