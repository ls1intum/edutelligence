from typing import List

from assessment_module_manager.app import app
from assessment_module_manager.module import ModuleResponse, request_to_module_by_exercise
from athena import ExerciseTypeVar


@app.post('/select_submission', responses={
    503: {
        "description": "Module is not available",
    },
})
async def select_submission(exercise: ExerciseTypeVar, submission_ids: List[int]) -> ModuleResponse[int]:
    """
    This endpoint is called by the LMS when a tutor wants to assess a submission.
    The LMS will pass the exercise and a list of submission IDs. The resulting submission ID will be given to the tutor.
    If the module returns -1, the LMS will select a random submission.
    """
    return await request_to_module_by_exercise(
        exercise,
        '/select_submission',
        {
            'exercise': exercise.dict(),
            'submission_ids': submission_ids,
        },
    )
