from pydantic import Field
from typing import Literal

from athena.text import Exercise, Submission
from athena.schemas.learner_profile import LearnerProfile
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.basic_approach.generate_suggestions import generate_suggestions
from module_text_llm.basic_approach.prompt_generate_suggestions import GenerateSuggestionsPrompt


class BasicApproachConfig(ApproachConfig):
    type: Literal['basic'] = 'basic'
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())
    
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool, is_graded: bool, learner_profile: LearnerProfile = None):
        return await generate_suggestions(exercise, submission, config, debug=debug, is_graded=is_graded)
    