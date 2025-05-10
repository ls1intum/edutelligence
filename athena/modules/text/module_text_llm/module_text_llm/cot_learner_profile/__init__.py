from pydantic import Field
from typing import Literal, Optional

from athena.text import Exercise, Submission
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
            feedback_alternative_standard=3,
            feedback_followup_summary=3,
            feedback_brief_detailed=3,
        )
    )

    async def generate_suggestions(
        self,
        exercise: Exercise,
        submission: Submission,
        config,
        *,
        debug: bool,
        is_graded: bool,
        learner_profile: Optional[LearnerProfile] = None
    ):

        from module_text_llm.cot_learner_profile.generate_suggestions import (
            generate_suggestions,
        )

        return await generate_suggestions(
            exercise,
            submission,
            config,
            debug=debug,
            is_graded=is_graded,
            learner_profile=learner_profile,
        )
