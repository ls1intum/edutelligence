import os

from pydantic import BaseModel, Field

import yaml

from ..common import Singleton
from ..llm.capability import RequirementList
from ..llm.capability.capability_checker import calculate_capability_scores
from ..llm.external import LanguageModel, AnyLLM


# Small workaround to get pydantic discriminators working
class LlmList(BaseModel):
    llms: list[AnyLLM] = Field(discriminator="type")


class LlmManager(metaclass=Singleton):
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
            raise Exception("LLM_CONFIG_PATH not set")

        with open(path, "r") as file:
            loaded_llms = yaml.safe_load(file)

        self.entries = LlmList.parse_obj({"llms": loaded_llms}).llms

    def get_llms_sorted_by_capabilities_score(
        self, requirements: RequirementList, invert_cost: bool = False
    ):
        """Get the llms sorted by their capability to requirement scores"""
        scores = calculate_capability_scores(
            [llm.capabilities for llm in self.entries], requirements, invert_cost
        )
        sorted_llms = sorted(zip(scores, self.entries), key=lambda pair: -pair[0])
        return [llm for _, llm in sorted_llms]
