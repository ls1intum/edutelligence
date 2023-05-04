from typing import List

from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, AvailableModuleNames, request_to_module_by_name

from athena.common.schemas import ExerciseType, Exercise, Submission, Feedback  # TODO: should be specific to exercise type


for exercise_type in ExerciseType:
    @app.post(
        "/" + exercise_type + "/{module_name}/feedback_suggestions",
        responses={
            503: {
                "description": "Module is not available",
            },
        },
        tags=[f"type:{exercise_type}", "action:feedback_suggestions"],
    )
    async def get_feedback_suggestions(
        module_name: AvailableModuleNames, exercise: Exercise, submission: Submission
    ) -> ModuleResponse[List[Feedback]]:
        """
        This endpoint is called by the LMS to get suggestions for feedback.
        """
        return await request_to_module_by_name(
            module_name,
            '/feedback_suggestions',
            {
                'exercise': exercise.dict(),
                'submission': submission.dict(),
            },
        )
