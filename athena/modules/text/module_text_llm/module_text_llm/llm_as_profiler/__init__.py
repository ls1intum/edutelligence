from pydantic import Field
from typing import Literal

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.llm_as_profiler.prompt_generate_feedback import GenerateSuggestionsPrompt
from module_text_llm.llm_as_profiler.prompt_profiler import ProfilerPrompt


class LLMAsProfilerConfig(ApproachConfig):
    type: Literal['llm_as_profiler'] = 'llm_as_profiler'
    profiler_prompt: ProfilerPrompt = Field(default=ProfilerPrompt())
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(
        default=GenerateSuggestionsPrompt()
    )
