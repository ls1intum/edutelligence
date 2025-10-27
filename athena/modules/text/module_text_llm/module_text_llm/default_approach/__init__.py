from pydantic import Field
from typing import Literal

from athena.schemas import LearnerProfile
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.default_approach.prompts import (
    GenerateSuggestionsPrompt,
    AnalysisPrompt,
    GenerateGradedSuggestionsPrompt,
)


class DefaultApproachConfig(ApproachConfig):
    """
    This is the default approach for the text LLM module to generate feedback.
    It generates the feedback in two stepts
        1. Analyze the submission
        2. Generate the feedback

    The analysis step makes use of the following inputs:
        - Problem statement
        - Example solution
        - Grading instructions
        - Student's submission
        - Student's previous submission (if provided)

    The feedback generation step makes use of the following inputs:
        - Analysis generated in the previous step
        - Problem statement
        - Example solution
        - Grading instructions
        - Student's feedback preferences (if provided)
    """
    type: Literal["default"] = "default"
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(
        default=GenerateSuggestionsPrompt()
    )
    analyze_submission_prompt: AnalysisPrompt = Field(
        default=AnalysisPrompt()
    )
    generate_graded_suggestions_prompt: GenerateGradedSuggestionsPrompt = Field(
        default=GenerateGradedSuggestionsPrompt()
    )
    learner_profile: LearnerProfile = Field(
        default=LearnerProfile(
            feedback_detail=2,
            feedback_formality=2,
        )
    )
