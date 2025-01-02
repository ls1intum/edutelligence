from llm_core.loaders.llm_config_loader import get_llm_config
from llm_core.models.model_config import ModelConfig
from pydantic import Field
from typing import Literal

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.chain_of_thought_approach.prompt_generate_feedback import CoTGenerateSuggestionsPrompt
from module_text_llm.chain_of_thought_approach.prompt_thinking import ThinkingPrompt

llm_config = get_llm_config()

class ChainOfThoughtConfig(ApproachConfig):
    # Defaults to the cheaper mini 4o model
    type: Literal['chain_of_thought'] = 'chain_of_thought'
    model: ModelConfig = Field(default=llm_config.models.base_model_config)
    thikning_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: CoTGenerateSuggestionsPrompt = Field(default=CoTGenerateSuggestionsPrompt())
    