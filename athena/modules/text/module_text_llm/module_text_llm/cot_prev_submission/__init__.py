from pydantic import Field
from typing import Literal

from athena.text import Exercise, Submission
from athena.schemas import LearnerProfile, Result

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.cot_prev_submission.prompt_generate_feedback import GenerateSuggestionsPrompt
from module_text_llm.cot_prev_submission.prompt_analyzer import AnalyzingPrompt
from module_text_llm.cot_prev_submission.generate_suggestions import generate_suggestions


class COTPrevSubmissionConfig(ApproachConfig):
    type: Literal['cot_prev_submission'] = 'cot_prev_submission'
    analyzing_prompt: AnalyzingPrompt = Field(default=AnalyzingPrompt())
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())
    profile: LearnerProfile = Field(default=LearnerProfile(
        feedback_alternative_standard=2,
        feedback_followup_summary=2,
        feedback_brief_detailed=2
    ))

    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool,
                                   is_graded: bool, learner_profile: LearnerProfile = None, result: Result = None):
        return await generate_suggestions(exercise, submission, config, debug=debug, is_graded=is_graded,
                                          learner_profile=learner_profile, result=result)
