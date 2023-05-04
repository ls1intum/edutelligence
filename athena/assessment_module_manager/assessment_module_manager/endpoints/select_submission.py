from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, AvailableModuleNames, request_to_module_by_name
from typing import List

from athena.common.schemas import ExerciseType, Exercise  # TODO: should be specific to exercise type


for exercise_type in ExerciseType:
    @app.post(
        "/" + exercise_type + "/{module_name}/select_submission",
        responses={
            503: {
                "description": "Module is not available",
            },
        },
        tags=[f"type:{exercise_type}", "action:select_submission"],
    )
    async def select_submission(
        module_name: AvailableModuleNames, exercise: Exercise, submission_ids: List[int]
    ) -> ModuleResponse[int]:
        """
        This endpoint is called by the LMS when a tutor wants to assess a submission.
        The LMS will pass the exercise and a list of submission IDs. The resulting submission ID will be given to the tutor.
        If the module returns -1, the LMS will select a random submission.
        """
        return await request_to_module_by_name(
            module_name,
            '/select_submission',
            {
                'exercise': exercise.dict(),
                'submission_ids': submission_ids,
            },
        )
