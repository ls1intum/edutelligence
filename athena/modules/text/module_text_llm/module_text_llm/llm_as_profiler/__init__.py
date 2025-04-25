from pydantic import Field
from typing import Literal

from athena.text import Exercise, Submission
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.llm_as_profiler.prompt_generate_feedback import GenerateSuggestionsPrompt
from module_text_llm.llm_as_profiler.prompt_profiler import ProfilerPrompt
from module_text_llm.llm_as_profiler.generate_suggestions import generate_suggestions


class LLMAsProfilerConfig(ApproachConfig):
    type: Literal['llm_as_profiler'] = 'llm_as_profiler'
    profiler_prompt: ProfilerPrompt = Field(default=ProfilerPrompt())
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())

    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool,
                                   is_graded: bool):
        return await generate_suggestions(exercise, submission, config, debug=debug, is_graded=is_graded)
