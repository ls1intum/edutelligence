"""Tool for retrieving additional exercise details."""

from datetime import datetime, timezone
from typing import Callable, Optional, Union

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
        - start_date: Exercise commencement (ISO-8601 string)
        - end_date: Exercise deadline (ISO-8601 string)
        - due_date_over: Optional[bool] - True if deadline passed, False if not, None if no end_date

        Returns:
            dict: Dictionary containing exercise timing details.
        """
        callback.in_progress("Reading exercise details...")
        current_time = datetime.now(tz=timezone.utc)

        # Format dates as ISO-8601 strings if they exist
        start_date = None
        end_date = None
        due_date_over = None

        if exercise:
            if exercise.start_date:
                # Ensure timezone awareness and convert to UTC if needed
                if exercise.start_date.tzinfo is None:
                    start_date = exercise.start_date.replace(
                        tzinfo=timezone.utc
                    ).isoformat()
                else:
                    start_date = exercise.start_date.astimezone(
                        timezone.utc
                    ).isoformat()

            if exercise.end_date:
                # Ensure timezone awareness and convert to UTC if needed
                if exercise.end_date.tzinfo is None:
                    end_date = exercise.end_date.replace(
                        tzinfo=timezone.utc
                    ).isoformat()
                else:
                    end_date = exercise.end_date.astimezone(timezone.utc).isoformat()

                # Calculate due_date_over as boolean
                end_datetime = exercise.end_date
                if end_datetime.tzinfo is None:
                    end_datetime = end_datetime.replace(tzinfo=timezone.utc)
                due_date_over = end_datetime < current_time

        return {
            "start_date": start_date if start_date else "No start date provided",
            "end_date": end_date if end_date else "No end date provided",
            "due_date_over": due_date_over,
        }

    return get_additional_exercise_details
