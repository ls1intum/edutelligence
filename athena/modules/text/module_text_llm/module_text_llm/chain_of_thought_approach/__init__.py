from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.chain_of_thought_approach.prompt_generate_feedback import CoTGenerateSuggestionsPrompt
from module_text_llm.chain_of_thought_approach.prompt_thinking import ThinkingPrompt
from module_text_llm.chain_of_thought_approach.generate_suggestions import generate_suggestions

class ChainOfThoughtConfig(ApproachConfig):
    type: Literal['chain_of_thought'] = 'chain_of_thought'
    thinking_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: CoTGenerateSuggestionsPrompt = Field(default=CoTGenerateSuggestionsPrompt())
    
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, debug: bool, is_graded: bool):
        return await generate_suggestions(exercise,submission,config,debug,is_graded)
    