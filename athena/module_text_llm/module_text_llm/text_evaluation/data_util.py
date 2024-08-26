from typing import List, Optional, Tuple

from module_text_llm.text_evaluation.evaluation_schemas import Exercise, Submission


def find_exercise_submission(
    exercises: List[Exercise],
    exercise_id_to_find: Optional[int] = None,
    submission_id_to_find: Optional[int] = None
) -> Tuple[Optional[Exercise], Optional[Submission]]:
    """Helper function to find exercise and submission based on given IDs."""
    exercise = next((ex for ex in exercises if ex.id == exercise_id_to_find),
                    exercises[0] if not exercise_id_to_find else None)
    if exercise:
        submission = next((sub for sub in exercise.submissions if sub.id == submission_id_to_find),
                          exercise.submissions[0] if not submission_id_to_find else None)
        return exercise, submission
    return None, None
