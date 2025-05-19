import os
from typing import Annotated

import yaml
from pydantic import BaseModel, Discriminator

from ..common.singleton import Singleton
from ..llm.external import AnyLlm
from .external.model import LanguageModel


# Small workaround to get pydantic discriminators working
class LlmList(BaseModel):
    llms: list[Annotated[AnyLlm, Discriminator("type")]]


class LlmManager(metaclass=Singleton):
    """LlmManager manages language model configurations and operations,
    including loading models from a configuration file."""

    entries: list[LanguageModel]

    def __init__(self):
        self.entries = []
        self.load_llms()

    def get_llm_by_id(self, llm_id):
        for llm in self.entries:
            if llm.id == llm_id:
                return llm

    def load_llms(self):
        """Load the llms from the config file"""
        path = os.environ.get("LLM_CONFIG_PATH")
        if not path:
            raise ValueError("LLM_CONFIG_PATH not set")

        with open(path, "r", encoding="utf-8") as file:
            loaded_llms = yaml.safe_load(file)

        self.entries = LlmList.model_validate({"llms": loaded_llms}).llms
