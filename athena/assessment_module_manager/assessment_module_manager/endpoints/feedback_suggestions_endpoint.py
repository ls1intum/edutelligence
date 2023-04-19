from typing import List

from assessment_module_manager.app import app
from assessment_module_manager.module import resolve_module, request_to_module
from athena import Exercise, Submission, Feedback


@app.post('/feedback_suggestions', responses={
    503: {
        "description": "Module is not available",
    },
})
async def get_feedback_suggestions(exercise: Exercise, submission: Submission) -> List[Feedback]:
    """
    This endpoint is called by the LMS to get suggestions for feedback.
    """
    suggestions_response = await request_to_module(
        resolve_module(exercise),
        '/feedback_suggestions',
        {
            'exercise': exercise.dict(),
            'submission': submission.dict(),
        },
    )
    return [Feedback.parse_obj(feedback) for feedback in suggestions_response.json()]
