"""Tool for retrieving the exercise list."""

from datetime import datetime
from typing import Callable, List, Optional

import pytz

from ..domain.data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_exercise_list(
    exercises: Optional[List[ExerciseWithSubmissionsDTO]], callback: StatusCallback
) -> Callable[[], List[dict]]:
    """
    Create a tool that retrieves the exercise list.

    Args:
        exercises: List of exercises with submissions.
        callback: Callback for status updates.

    Returns:
        Callable[[], List[dict]]: Function that returns the list of exercises.
    """

    def get_exercise_list() -> list[dict]:
        """
        Get the list of exercises in the course.
        Use this if the student asks you about an exercise.
        Note: The exercise contains a list of submissions (timestamp and score) of this student so you
        can provide additional context regarding their progress and tendencies over time.
        Also, ensure to use the provided current date and time and compare it to the start date and due date etc.
        Do not recommend that the student should work on exercises with a past due date.
        The submissions array tells you about the status of the student in this exercise:
        You see when the student submitted the exercise and what score they got.
        A 100% score means the student solved the exercise correctly and completed it.

        Returns:
            list[dict]: List of exercise data without problem statements.
        """
        callback.in_progress("Reading exercise list ...")
        if not exercises:
            return []

        current_time = datetime.now(tz=pytz.UTC)
        result = []
        for exercise in exercises:
            exercise_dict = exercise.model_dump()
            exercise_dict["due_date_over"] = (
                exercise.due_date < current_time if exercise.due_date else None
            )
            # remove the problem statement from the exercise dict
            exercise_dict.pop("problem_statement", None)
            result.append(exercise_dict)
        return result

    return get_exercise_list
