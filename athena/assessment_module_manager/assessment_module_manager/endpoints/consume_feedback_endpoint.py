from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, AvailableModuleNames, request_to_module_by_name
from athena.common.schemas import ExerciseType, Exercise, Submission, Feedback  # TODO: should be specific to exercise type


for exercise_type in ExerciseType:
    @app.post(
        "/" + exercise_type + "/{module_name}/feedback",
        responses={
            503: {
                "description": "Module is not available",
            },
        },
        tags=[f"type:{exercise_type}", "action:feedback"],
    )
    async def consume_feedback(
        module_name: AvailableModuleNames, exercise: Exercise, submission: Submission, feedback: Feedback
    ) -> ModuleResponse:
        """
        This endpoint is called by the LMS whenever there is a new feedback to process.
        """
        return await request_to_module_by_name(
            module_name,
            '/feedback',
            {
                'exercise': exercise.dict(),
                'submission': submission.dict(),
                'feedback': feedback.dict(),
            },
        )
