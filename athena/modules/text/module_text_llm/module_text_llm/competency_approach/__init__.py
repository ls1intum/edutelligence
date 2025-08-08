from pydantic import Field
from typing import Literal
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.competency_approach.prompt_generate_suggestions import (
    GenerateSuggestionsPrompt,
)
from module_text_llm.competency_approach.prompt_submission_analysis import (
    AnalysisPrompt,
)

class CompetencyApproachConfig(ApproachConfig):
    type: Literal["competency"] = "competency"
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(
        default=GenerateSuggestionsPrompt()
    )
    analyze_submission_prompt: AnalysisPrompt = Field(
        default=AnalysisPrompt()
    )
