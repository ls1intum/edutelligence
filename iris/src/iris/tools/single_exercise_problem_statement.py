from typing import Callable

from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.web.status.status_update import StatusCallback


def create_tool_get_problem_statement(
    dto: TextExerciseDTO | ProgrammingExerciseDTO,
    callback: StatusCallback,
) -> Callable[[], str]:
    """
    Create a tool that retrieves the problem statement of an exercise.
    Args:
        dto (TextExerciseDTO | ProgrammingExerciseDTO): DTO containing exercise data.
        callback (StatusCallback): Callback for status updates.
    Returns:
        Callable[[], str]: Function that returns the problem statement.
    """

    def get_problem_statement() -> str:
        """
        Get the problem statement of the exercise.
        Use this if the student asks you about the problem statement of a text or programming exercise.
        Returns:
            str: The problem statement or an error message if not found.
        """
        callback.in_progress("Reading problem statement ...")
        return dto.problem_statement or "No problem statement provided"

    return get_problem_statement
