import os
from pathlib import Path

import yaml
from pydantic import BaseModel

import logging

logger = logging.getLogger(__name__)


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
        file_path_env = os.environ.get("APPLICATION_YML_PATH") or str(Path(__file__).parent.parent / "application.yml")
        logger.info(f"Loading settings from: {file_path_env}")
        
        if not file_path_env:
            logger.error("APPLICATION_YML_PATH environment variable is not set")
            raise OSError("APPLICATION_YML_PATH environment variable is not set.")

        file_path = Path(file_path_env)
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found at {file_path}.")

        try:
            with open(file_path, encoding="utf-8") as file:
                settings_file = yaml.safe_load(file)
                logger.info(f"Loaded settings: {settings_file}")
            return cls.model_validate(settings_file)
        except FileNotFoundError as e:
            logger.error(f"Configuration file not found at {file_path}")
            raise FileNotFoundError(
                f"Configuration file not found at {file_path}."
            ) from e
        except yaml.YAMLError as e:
            raise ValueError(
                f"YAML parsing error in configuration file {file_path}: {e}"
            ) from e
        
    @classmethod
    def get_api_keys(cls):
        return cls.get_settings().api_keys

settings = Settings.get_settings()