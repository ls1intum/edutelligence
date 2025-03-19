import os
from typing import Annotated

import yaml
from pydantic import BaseModel, Discriminator

from ..common.singleton import Singleton
from ..llm.capability import RequirementList
from ..llm.capability.capability_checker import (
    calculate_capability_scores,
    capabilities_fulfill_requirements,
)
from ..llm.external import AnyLlm
from .external.model import LanguageModel


# Small workaround to get pydantic discriminators working
class LlmList(BaseModel):
    llms: list[Annotated[AnyLlm, Discriminator("type")]]


class LlmManager(metaclass=Singleton):
    """LlmManager manages language model configurations and operations, including loading models from a configuration
    file and sorting them by capability scores."""

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

    def get_llms_sorted_by_capabilities_score(
        self, requirements: RequirementList, invert_cost: bool = False
    ):
        """Get the llms sorted by their capability to requirement scores"""
        valid_llms = [
            llm
            for llm in self.entries
            if capabilities_fulfill_requirements(
                llm.capabilities, requirements
            )
        ]
        scores = calculate_capability_scores(
            [llm.capabilities for llm in valid_llms], requirements, invert_cost
        )
        sorted_llms = sorted(
            zip(scores, valid_llms), key=lambda pair: -pair[0]
        )
        return [llm for _, llm in sorted_llms]
