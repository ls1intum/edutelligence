import os
from pathlib import Path
from pydantic import BaseModel
import yaml


class APIKeyConfig(BaseModel):
    token: str


class Settings(BaseModel):
    api_keys: list[APIKeyConfig]

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
            with open(file_path, "r") as file:
                settings_file = yaml.safe_load(file)
            return cls.parse_obj(settings_file)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Configuration file not found at {file_path}."
            ) from e
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML file at {file_path}.") from e


settings = Settings.get_settings()
