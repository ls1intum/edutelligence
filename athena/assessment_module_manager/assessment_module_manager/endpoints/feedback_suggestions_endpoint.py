from typing import List

from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, request_to_module_by_exercise
from athena import ExerciseTypeVar, Submission, Feedback


@app.post('/feedback_suggestions', responses={
    503: {
        "description": "Module is not available",
    },
})
async def get_feedback_suggestions(exercise: ExerciseTypeVar, submission: Submission) -> ModuleResponse[List[Feedback]]:
    """
    This endpoint is called by the LMS to get suggestions for feedback.
    """
    return await request_to_module_by_exercise(
        exercise,
        '/feedback_suggestions',
        {
            'exercise': exercise.dict(),
            'submission': submission.dict(),
        },
    )
