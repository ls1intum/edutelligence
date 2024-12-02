from pydantic import BaseModel, Field
from typing import Literal
from llm_core.models import ModelConfigType, OllamaModelConfig

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.ollama_chain_of_thought_approach.prompt_generate_feedback import CoTGenerateSuggestionsPrompt
from module_text_llm.ollama_chain_of_thought_approach.prompt_thinking import ThinkingPrompt

class OllamaChainOfThoughtConfig(ApproachConfig):
    # Defaults to the cheaper mini 4o model
    type: Literal['ollama_chain_of_thought'] = 'ollama_chain_of_thought'
    model: ModelConfigType = Field(default=OllamaModelConfig)  # type: ignore
    thikning_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: CoTGenerateSuggestionsPrompt = Field(default=CoTGenerateSuggestionsPrompt())
    