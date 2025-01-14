from module_text_llm.approach_config import ApproachConfig
from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission
from module_text_llm.self_consistency.prompt_generate_suggestions import GenerateSuggestionsPrompt
from module_text_llm.self_consistency.generate_suggestions import generate_suggestions
class SelfConsistencyConfig(ApproachConfig):
    type: Literal['self'] = 'self'
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())
    
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, debug: bool):
        return await generate_suggestions(exercise,submission,config,debug)