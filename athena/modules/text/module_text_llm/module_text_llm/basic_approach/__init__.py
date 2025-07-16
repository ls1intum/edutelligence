from pydantic import Field
from typing import Literal
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.basic_approach.prompt_generate_suggestions import (
    GenerateSuggestionsPrompt,
)
from module_text_llm.basic_approach.prompt_submission_analysis import (
    AnalysisPrompt,
)

class BasicApproachConfig(ApproachConfig):
    type: Literal["basic"] = "basic"
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(
        default=GenerateSuggestionsPrompt()
    )
    analyze_submission_prompt: AnalysisPrompt = Field(
        default=AnalysisPrompt()
    )
