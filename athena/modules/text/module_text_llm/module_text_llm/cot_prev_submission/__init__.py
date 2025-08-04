from pydantic import Field
from typing import Literal

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.cot_prev_submission.prompt_generate_feedback import GenerateSuggestionsPrompt
from module_text_llm.cot_prev_submission.prompt_analyzer import AnalyzingPrompt


class COTPrevSubmissionConfig(ApproachConfig):
    type: Literal['cot_prev_submission'] = 'cot_prev_submission'
    analyzing_prompt: AnalyzingPrompt = Field(default=AnalyzingPrompt())
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(
        default=GenerateSuggestionsPrompt()
    )
