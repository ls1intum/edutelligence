from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.cot_learner_profile.prompt_generate_feedback import GenerateSuggestionsPrompt
from module_text_llm.cot_learner_profile.prompt_thinking import ThinkingPrompt
from module_text_llm.cot_learner_profile.generate_suggestions import generate_suggestions
from athena.schemas.learner_profile import LearnerProfile


class COTLearnerProfileConfig(ApproachConfig):
    type: Literal['cot_learner_profile'] = 'cot_learner_profile'
    thinking_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())

    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool,
                                   is_graded: bool, learner_profile: LearnerProfile = None):
        return await generate_suggestions(exercise, submission, config, debug, is_graded, learner_profile)
