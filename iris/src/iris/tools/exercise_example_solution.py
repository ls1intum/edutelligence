from typing import Callable

from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.web.status.status_update import StatusCallback


def create_tool_get_example_solution(
    dto: TextExerciseDTO,
    callback: StatusCallback,
) -> Callable[[], str]:
    """
    Create a tool that retrieves the example solution of a text exercise.
    Args:
        dto (TextExerciseDTO): DTO containing text exercise data.
        callback (StatusCallback): Callback for status updates.
    Returns:
        Callable[[], str]: Function that returns the example solution.
    """

    def get_example_solution() -> str:
        """
        Get the example solution of the text exercise.
        Use this if the student asks you about the example solution of a text exercise.
        Returns:
            str: The example solution or an error message if not found.
        """
        callback.in_progress("Reading example solution ...")
        return dto.example_solution or "No example solution provided"

    return get_example_solution
