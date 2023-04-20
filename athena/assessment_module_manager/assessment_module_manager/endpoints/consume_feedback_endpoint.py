from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, request_to_module_by_exercise
from athena import Exercise, Submission, Feedback


@app.post('/feedback', responses={
    503: {
        "description": "Module is not available",
    },
})
async def consume_feedback(exercise: Exercise, submission: Submission, feedback: Feedback) -> ModuleResponse:
    """
    This endpoint is called by the LMS whenever there is a new feedback to process.
    """
    return await request_to_module_by_exercise(
        exercise,
        '/feedback',
        {
            'exercise': exercise.dict(),
            'submission': submission.dict(),
            'feedback': feedback.dict(),
        },
    )
