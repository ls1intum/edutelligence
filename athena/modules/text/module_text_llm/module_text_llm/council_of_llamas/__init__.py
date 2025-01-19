from module_text_llm.approach_config import ApproachConfig
from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission
from module_text_llm.council_of_llamas.generate_suggestions import generate_suggestions
from module_text_llm.council_of_llamas.prompt_generate_suggestions import GenerateSuggestionsPrompt

class CouncilOfLlamasConfig(ApproachConfig):
    type: Literal['council_of_llamas'] = 'council_of_llamas'
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())
    
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config,*, debug: bool, is_graded: bool):
        return await generate_suggestions(exercise, submission, config, debug, is_graded)