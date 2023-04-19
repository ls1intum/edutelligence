from fastapi import status

from assessment_module_manager.app import app
from assessment_module_manager.module import resolve_module, request_to_module
from athena import Exercise, Submission


@app.post('/submissions', status_code=status.HTTP_204_NO_CONTENT, responses={
    503: {
        "description": "Module is not available",
    },
})
async def consume_submissions(exercise: Exercise, submissions: list[Submission]):
    """
    This endpoint is called by the LMS when the exercise deadline is over and
    the submissions need to be processed.
    """
    await request_to_module(
        resolve_module(exercise),
        '/submissions',
        {
            'exercise': exercise.dict(),
            'submissions': [submission.dict() for submission in submissions],
        },
    )
