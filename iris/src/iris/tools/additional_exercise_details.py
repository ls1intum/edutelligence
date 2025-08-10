"""Tool for retrieving additional exercise details."""

from datetime import datetime
from typing import Callable, Optional, Union

import pytz

from ..domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from ..domain.data.text_exercise_dto import TextExerciseDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_additional_exercise_details(
    exercise: Optional[Union[ProgrammingExerciseDTO, TextExerciseDTO]],
    callback: StatusCallback,
) -> Callable[[], dict]:
    """
    Create a tool that retrieves additional exercise details.

    Args:
        exercise: Exercise data (ProgrammingExerciseDTO or TextExerciseDTO).
        callback: Callback for status updates.

    Returns:
        Function that returns exercise details.
    """

    def get_additional_exercise_details() -> dict:
        """
        # Additional Exercise Details Tool

        ## Purpose
        Retrieve time-related information about the exercise for context and deadline awareness.

        ## Retrieved Information
        - start_date: Exercise commencement
        - end_date: Exercise deadline
        - due_date_over: Boolean indicating if the deadline has passed

        Returns:
            dict: Dictionary containing exercise timing details.
        """
        callback.in_progress("Reading exercise details...")
        current_time = datetime.now(tz=pytz.UTC)
        return {
            "start_date": (
                exercise.start_date if exercise else "No start date provided"
            ),
            "end_date": (exercise.end_date if exercise else "No end date provided"),
            "due_date_over": (
                exercise.end_date < current_time
                if exercise and exercise.end_date
                else "No end date provided"
            ),
        }

    return get_additional_exercise_details
