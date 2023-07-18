import os

from pyaml_env import parse_config
from pydantic import BaseModel


class LLMModelConfig(BaseModel):
    name: str
    description: str
    llm_credentials: dict


class APIKeyConfig(BaseModel):
    token: str
    comment: str
    llm_access: list[str]


class Settings(BaseModel):
    class PyrisSettings(BaseModel):
        api_keys: list[APIKeyConfig]
        llms: dict[str, LLMModelConfig]

    pyris: PyrisSettings

    @classmethod
    def get_settings(cls):
        if "RUN_ENV" in os.environ and os.environ["RUN_ENV"] == "test":
            file_path = "application.test.yml"
        else:
            file_path = "application.yml"

        return Settings.parse_obj(parse_config(file_path))


settings = Settings.get_settings()
