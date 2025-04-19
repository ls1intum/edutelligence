from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.llm_as_profiler.prompt_generate_feedback import GenerateSuggestionsPrompt
from module_text_llm.llm_as_profiler.prompt_thinking import ThinkingPrompt
from module_text_llm.llm_as_profiler.generate_suggestions import generate_suggestions
from athena.schemas.learner_profile import LearnerProfile


class LLMAsProfilerConfig(ApproachConfig):
    type: Literal['llm_as_profiler'] = 'llm_as_profiler'
    thinking_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())

    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool,
                                   is_graded: bool, learner_profile: LearnerProfile = None):
        return await generate_suggestions(exercise, submission, config, debug, is_graded, learner_profile)
