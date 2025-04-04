from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.personalized_approach.prompt_generate_feedback import GenerateSuggestionsPrompt
from module_text_llm.personalized_approach.prompt_thinking import ThinkingPrompt
from module_text_llm.personalized_approach.generate_suggestions import generate_suggestions
from athena.schemas.learner_profile import LearnerProfile


class PersonalizedConfig(ApproachConfig):
    type: Literal['personalized'] = 'personalized'
    thinking_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())

    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool,
                                   is_graded: bool, learner_profile: LearnerProfile = None):
        return await generate_suggestions(exercise, submission, config, debug, is_graded, learner_profile)
