import os
from pydantic import BaseModel
from pyaml_env import parse_config


class Settings(BaseModel):
    class PyrisSettings(BaseModel):
        api_key: str
        llm: dict

    pyris: PyrisSettings

    @classmethod
    def get_settings(cls):
        if "RUN_ENV" in os.environ and os.environ["RUN_ENV"] == "test":
            file_path = "application.test.yml"
        else:
            file_path = "application.yml"

        return Settings.parse_obj(parse_config(file_path))


settings = Settings.get_settings()
