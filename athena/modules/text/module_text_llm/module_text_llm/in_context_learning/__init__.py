from module_text_llm.approach_config import ApproachConfig
from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission


from module_text_llm.in_context_learning.prompt_generate_suggestions import GenerateSuggestionsPrompt
from module_text_llm.in_context_learning.generate_suggestions import generate_suggestions

class InContextLearningConfig(ApproachConfig):
    type: Literal['icl'] = 'icl'
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())
    
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, debug: bool):
        return await generate_suggestions(exercise,submission,config,debug)