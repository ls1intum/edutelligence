from pydantic import Field
from typing import Literal

from athena.schemas.learner_profile import LearnerProfile
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.cot_learner_profile.prompt_generate_feedback import (
    GenerateSuggestionsPrompt,
)
from module_text_llm.cot_learner_profile.prompt_thinking import ThinkingPrompt


class COTLearnerProfileConfig(ApproachConfig):
    type: Literal["cot_learner_profile"] = "cot_learner_profile"
    thinking_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(
        default=GenerateSuggestionsPrompt()
    )
    profile: LearnerProfile = Field(
        default=LearnerProfile(
            feedback_alternative_standard=2,
            feedback_followup_summary=2,
            feedback_brief_detailed=2,
        )
    )
