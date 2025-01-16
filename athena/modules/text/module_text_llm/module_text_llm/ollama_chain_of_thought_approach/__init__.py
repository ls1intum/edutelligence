from pydantic import Field
from typing import Literal
from llm_core.models import ModelConfigType
from athena.text import Exercise, Submission
try:
    from llm_core.models import OllamaModelConfig
except ImportError as e:
    print(f"Warning: Failed to import models. {e}")
    OllamaModelConfig = None
    
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.ollama_chain_of_thought_approach.prompt_generate_feedback import CoTGenerateSuggestionsPrompt
from module_text_llm.ollama_chain_of_thought_approach.prompt_thinking import ThinkingPrompt
from module_text_llm.ollama_chain_of_thought_approach.generate_suggestions import generate_suggestions
class OllamaChainOfThoughtConfig(ApproachConfig):
    type: Literal['ollama_chain_of_thought'] = 'ollama_chain_of_thought'
    model: ModelConfigType = Field(default=OllamaModelConfig)  # type: ignore
    thinking_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: CoTGenerateSuggestionsPrompt = Field(default=CoTGenerateSuggestionsPrompt())
    
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool, is_graded: bool):
        return await generate_suggestions(exercise,submission,config,debug,is_graded)  