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


class CacheSettings(BaseModel):
    class CacheParams(BaseModel):
        host: str
        port: int

    hazelcast: CacheParams


class Settings(BaseModel):
    class PyrisSettings(BaseModel):
        api_keys: list[APIKeyConfig]
        llms: dict[str, LLMModelConfig]
        cache: CacheSettings

    pyris: PyrisSettings

    @classmethod
    def get_settings(cls):
        postfix = "-docker" if "DOCKER" in os.environ else ""
        if "RUN_ENV" in os.environ and os.environ["RUN_ENV"] == "test":
            file_path = f"application{postfix}.test.yml"
        else:
            file_path = f"application{postfix}.yml"

        return Settings.parse_obj(parse_config(file_path))


settings = Settings.get_settings()
