from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, request_to_module_by_exercise
from athena import ExerciseTypeVar, Submission


@app.post('/submissions', responses={
    503: {
        "description": "Module is not available",
    },
})
async def consume_submissions(exercise: ExerciseTypeVar, submissions: list[Submission]) -> ModuleResponse:
    """
    This endpoint is called by the LMS when the exercise deadline is over and
    the submissions need to be processed.
    """
    return await request_to_module_by_exercise(
        exercise,
        '/submissions',
        {
            'exercise': exercise.dict(),
            'submissions': [submission.dict() for submission in submissions],
        },
    )
