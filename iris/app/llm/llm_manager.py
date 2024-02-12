import os

from pydantic import BaseModel, Field

import yaml

from common import Singleton
from llm.wrapper import AbstractLlmWrapper, LlmWrapper


# Small workaround to get pydantic discriminators working
class LlmList(BaseModel):
    llms: list[LlmWrapper] = Field(discriminator="type")


class LlmManager(metaclass=Singleton):
    entries: list[AbstractLlmWrapper]

    def __init__(self):
        self.entries = []
        self.load_llms()

    def get_llm_by_id(self, llm_id):
        for llm in self.entries:
            if llm.id == llm_id:
                return llm

    def load_llms(self):
        path = os.environ.get("LLM_CONFIG_PATH")
        if not path:
            raise Exception("LLM_CONFIG_PATH not set")

        with open(path, "r") as file:
            loaded_llms = yaml.safe_load(file)

        self.entries = LlmList.parse_obj({"llms": loaded_llms}).llms
