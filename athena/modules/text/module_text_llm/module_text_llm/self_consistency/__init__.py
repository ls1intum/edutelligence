from pydantic import Field
from typing import Literal

from module_text_llm.self_consistency.prompt_generate_suggestions import GenerateSuggestionsPrompt
from module_text_llm.approach_config import ApproachConfig


class SelfConsistencyConfig(ApproachConfig):
    type: Literal['self_consistency'] = 'self_consistency'
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())