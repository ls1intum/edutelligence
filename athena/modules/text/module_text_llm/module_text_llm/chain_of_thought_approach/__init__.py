from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission

from module_text_llm.approach_config import ApproachConfig
from module_text_llm.chain_of_thought_approach.prompt_generate_feedback import CoTGenerateSuggestionsPrompt
from module_text_llm.chain_of_thought_approach.prompt_thinking import ThinkingPrompt
from module_text_llm.chain_of_thought_approach.generate_suggestions import generate_suggestions
from athena.schemas.learner_profile import LearnerProfile

class ChainOfThoughtConfig(ApproachConfig):
    type: Literal['chain_of_thought'] = 'chain_of_thought'
    thinking_prompt: ThinkingPrompt = Field(default=ThinkingPrompt())
    generate_suggestions_prompt: CoTGenerateSuggestionsPrompt = Field(default=CoTGenerateSuggestionsPrompt())
    learner_profile: LearnerProfile = Field(default=LearnerProfile(
        feedback_practical_theoretical=1,
        feedback_creative_guidance=1,
        feedback_followup_summary=1,
        feedback_brief_detailed=5))
    
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool, is_graded: bool, learner_profile: LearnerProfile = None):
        return await generate_suggestions(exercise,submission,config,debug,is_graded)
    