import os
import types
import copy
from guidance.llms import OpenAI
import guidance.llms._openai
from pyaml_env import parse_config
from pydantic import BaseModel, validator

old_add_text_to_chat_mode = guidance.llms._openai.add_text_to_chat_mode


def new_add_text_to_chat_mode(chat_mode):
    if isinstance(chat_mode, (types.AsyncGeneratorType, types.GeneratorType)):
        return guidance.llms._openai.add_text_to_chat_mode_generator(chat_mode)
    else:
        for c in chat_mode["choices"]:
            if "message" in c and "content" in c["message"]:
                c["text"] = c["message"]["content"]
            else:
                c["text"] = " "
        return chat_mode


guidance.llms._openai.add_text_to_chat_mode = new_add_text_to_chat_mode


class LLMModelSpecs(BaseModel):
    context_length: int


class LLMModelConfig(BaseModel):
    type: str
    name: str
    description: str

    def get_instance(cls):
        raise NotImplementedError()


class OpenAIConfig(LLMModelConfig):
    spec: LLMModelSpecs
    llm_credentials: dict

    @validator("type")
    def check_type(cls, v):
        if v != "openai":
            raise ValueError("Invalid type:" + v + " != openai")
        return v

    def get_instance(cls):
        print("Specs", cls.llm_credentials)
        llm_credentials = copy.deepcopy(cls.llm_credentials)
        return OpenAI(**llm_credentials)


class StrategyLLMConfig(LLMModelConfig):
    llms: list[str]

    @validator("type")
    def check_type(cls, v):
        if v != "strategy":
            raise ValueError("Invalid type:" + v + " != strategy")
        return v

    def get_instance(cls):
        from app.llms.strategy_llm import StrategyLLM

        return StrategyLLM(cls.llms)


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
        llms: dict[str, OpenAIConfig | StrategyLLMConfig]
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

# Init instance, so it is faster during requests
for value in enumerate(settings.pyris.llms.values()):
    value[1].get_instance()
