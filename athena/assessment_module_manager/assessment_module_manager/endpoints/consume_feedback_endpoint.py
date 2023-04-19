from fastapi import status

from assessment_module_manager.app import app
from assessment_module_manager.module import resolve_module, request_to_module
from athena import Exercise, Submission, Feedback


@app.post('/feedback', status_code=status.HTTP_204_NO_CONTENT, responses={
    503: {
        "description": "Module is not available",
    },
})
async def consume_feedback(exercise: Exercise, submission: Submission, feedback: Feedback):
    """
    This endpoint is called by the LMS whenever there is a new feedback to process.
    """
    await request_to_module(
        resolve_module(exercise),
        '/feedback',
        {
            'exercise': exercise.dict(),
            'submission': submission.dict(),
            'feedback': feedback.dict(),
        },
    )
