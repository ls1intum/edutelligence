"""Tool for retrieving an exercise problem statement."""

from typing import Callable, List, Optional

from ..domain.data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_exercise_problem_statement(
    exercises: Optional[List[ExerciseWithSubmissionsDTO]], callback: StatusCallback
) -> Callable[[int], str]:
    """
    Create a tool that retrieves an exercise problem statement.

    Args:
        exercises: List of exercises with submissions.
        callback: Callback for status updates.

    Returns:
        Callable[[int], str]: Function that returns the problem statement.
    """

    def get_exercise_problem_statement(exercise_id: int) -> str:
        """
        Get the problem statement of the exercise with the given ID.
        Use this if the student asks you about the problem statement of an exercise or if you need
        to know more about the content of an exercise to provide more informed advice.
        Important: You have to pass the correct exercise ID here.
        DO IT ONLY IF YOU KNOW THE ID DEFINITELY. NEVER GUESS THE ID.
        Note: This operation is idempotent. Repeated calls with the same ID will return the same output.
        You can only use this if you first queried the exercise list and looked up the ID of the exercise.

        Args:
            exercise_id (int): The ID of the exercise.

        Returns:
            str: The problem statement or an error message if not found.
        """
        callback.in_progress(
            f"Reading exercise problem statement (id: {exercise_id}) ..."
        )
        if not exercises:
            return "No exercises available"

        exercise = next((ex for ex in exercises if ex.id == exercise_id), None)
        if exercise:
            return exercise.problem_statement or "No problem statement provided"
        else:
            return "Exercise not found"

    return get_exercise_problem_statement
