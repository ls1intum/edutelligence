from pydantic import BaseModel, Field
from typing import Literal
from llm_core.models import ModelConfigType
try:
    from llm_core.models import OllamaModelConfig
except ImportError as e:
    print(f"Warning: Failed to import models. {e}")
    OllamaModelConfig = None
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.ollama_chain_of_thought_approach.prompt_generate_feedback import CoTGenerateSuggestionsPrompt
from module_text_llm.ollama_chain_of_thought_approach.prompt_thinking import ThinkingPrompt

class OllamaChainOfThoughtConfig(ApproachConfig):
    type: Literal['ollama_chain_of_thought'] = 'ollama_chain_of_thought'
    model: ModelConfigType = Field(default=OllamaModelConfig)  # type: ignore
    thikning_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: CoTGenerateSuggestionsPrompt = Field(default=CoTGenerateSuggestionsPrompt())
    