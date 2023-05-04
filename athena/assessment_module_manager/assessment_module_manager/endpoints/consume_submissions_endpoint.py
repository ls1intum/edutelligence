from typing import List

from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, AvailableModuleNames, request_to_module_by_name

from athena.common.schemas import ExerciseType, Exercise, Submission  # TODO: should be specific to exercise type


for exercise_type in ExerciseType:
    @app.post(
        "/" + exercise_type + "/{module_name}/submissions",
        responses={
            503: {
                "description": "Module is not available",
            },
        },
        tags=[f"type:{exercise_type}", "action:submissions"],
    )
    async def consume_submissions(
        module_name: AvailableModuleNames, exercise: Exercise, submissions: List[Submission]
    ) -> ModuleResponse:
        """
        This endpoint is called by the LMS when the exercise deadline is over and
        the submissions need to be processed.
        """
        return await request_to_module_by_name(
            module_name,
            '/submissions',
            {
                'exercise': exercise.dict(),
                'submissions': [submission.dict() for submission in submissions],
            },
        )
