from athena.logger import logger
from typing import List, Optional
from athena import feedback_provider
from athena.modeling import Exercise, Submission, Feedback
from athena.schemas import LearnerProfile
from module_modeling_llm.config import Configuration
from module_modeling_llm.utils.get_exercise_model import get_exercise_model
from module_modeling_llm.core.get_structured_grading_instructions import (
    get_structured_grading_instructions,
)
from module_modeling_llm.core.generate_suggestions import generate_suggestions
from module_modeling_llm.core.filter_feedback import filter_feedback
from module_modeling_llm.utils.convert_to_athana_feedback_model import (
    convert_to_athana_feedback_model,
)


@feedback_provider
async def suggest_feedback(
    exercise: Exercise,
    submission: Submission,
    is_graded: bool,
    module_config: Configuration,
    learner_profile: Optional[LearnerProfile] = None,
) -> List[Feedback]:
    logger.info(
        "suggest_feedback: Suggestions for submission %d of exercise %d were requested",
        submission.id,
        exercise.id,
    )
    exercise_model = get_exercise_model(exercise, submission)
    structured = await get_structured_grading_instructions(
        exercise_model=exercise_model,
        config=module_config.approach,
        grading_instructions=exercise.grading_instructions,
        grading_criteria=exercise.grading_criteria,
        debug=module_config.debug,
    )
    assessment = await generate_suggestions(
        exercise_model=exercise_model,
        structured_grading_instructions=structured,
        config=module_config.approach,
        debug=module_config.debug,
    )
    if not is_graded:
        assessment = await filter_feedback(
            exercise=exercise_model,
            original_feedback=assessment,
            config=module_config.approach,
            debug=module_config.debug,
        )
    return convert_to_athana_feedback_model(
        feedback_result=assessment,
        exercise_model=exercise_model,
        manual_structured_grading_instructions=exercise.grading_criteria,
    )
