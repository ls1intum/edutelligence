from typing import List, Annotated
from fastapi import APIRouter, Depends, Body
from dependency_injector.wiring import inject, Provide

from athena.modeling import Exercise, Feedback, Submission
from athena.schemas import LearnerProfile
from athena.module_config import get_dynamic_module_config_factory
from athena.logger import logger

from .container import AppContainer
from .config import Configuration
from .core.filter_feedback import filter_feedback
from .core.generate_suggestions import generate_suggestions
from .core.get_structured_grading_instructions import (
    get_structured_grading_instructions,
)
from .utils.convert_to_athana_feedback_model import convert_to_athana_feedback_model
from .utils.get_exercise_model import get_exercise_model

router = APIRouter()


# This is our new, injectable dependency for the module configuration.
# It handles the override logic cleanly.
def get_final_config(
    default_config: Annotated[
        Configuration, Depends(Provide[AppContainer.module_config])
    ],
    dynamic_config: Annotated[
        Configuration, Depends(get_dynamic_module_config_factory(Configuration))
    ],
) -> Configuration:
    # `dynamic_config` comes from the request header and might have user-overrides.
    # We merge it into our default config.
    # The `approach` section is the most likely to be overridden.
    if dynamic_config.approach:
        # Create a new config so we don't modify the singleton default
        merged_config = default_config.copy(deep=True)
        # Update with non-None values from the dynamic config
        update_data = dynamic_config.approach.dict(exclude_unset=True)
        if update_data:
            merged_config.approach = merged_config.approach.copy(update=update_data)
        return merged_config
    return default_config


@router.post("/feedback_suggestions", response_model=List[Feedback])
@inject
async def suggest_feedback(
    exercise: Exercise,
    submission: Submission,
    is_graded: bool = Body(True, alias="isGraded"),
    learner_profile: LearnerProfile | None = Body(
        None, alias="learnerProfile"
    ),  # Assuming this might be used later
    module_config: Configuration = Depends(get_final_config),
) -> List[Feedback]:
    logger.info(
        "suggest_feedback: Suggestions for submission %d of exercise %d were requested",
        submission.id,
        exercise.id,
    )

    exercise_model = get_exercise_model(exercise, submission)

    structured_grading_instructions = await get_structured_grading_instructions(
        exercise_model,
        module_config.approach,
        exercise.grading_instructions,
        exercise.grading_criteria,
        module_config.debug,
    )

    feedback_suggestions = await generate_suggestions(
        exercise_model,
        structured_grading_instructions,
        module_config.approach,
        module_config.debug,
    )

    if not is_graded:
        feedback_suggestions = await filter_feedback(
            exercise_model,
            feedback_suggestions,
            module_config.approach,
            module_config.debug,
        )

    return convert_to_athana_feedback_model(feedback_suggestions, exercise_model)