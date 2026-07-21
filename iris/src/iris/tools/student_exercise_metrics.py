"""Tool for retrieving student exercise metrics."""

from typing import Callable, Dict, List, Optional, Union

from ..domain.data.metrics.student_metrics_dto import StudentMetricsDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_student_exercise_metrics(
    metrics: Optional[StudentMetricsDTO], callback: StatusCallback
) -> Callable[[List[int]], Union[Dict[int, dict], str]]:
    """
    Create a tool that retrieves student exercise metrics.

    Args:
        metrics: Student metrics data.
        callback: Callback for status updates.

    Returns:
        Callable[[List[int]], Union[Dict[int, dict], str]]: Function to get metrics.
    """
    del callback

    def get_student_exercise_metrics(
        exercise_ids: List[int],
    ) -> Union[Dict[int, dict], str]:
        """
        Get the student exercise metrics for the given exercises.
        This is the authoritative source for the student's exercise scores,
        submission timing, and comparisons with the course average. For a
        performance overview or dashboard request, first use the exercise list
        to resolve the real exercise IDs, then call this tool for those IDs.
        If competency-level context is relevant, use the competency list as
        additional evidence; competency progress is not a substitute for these
        exercise-specific metrics.
        Important: You have to pass the correct exercise ids here. If you don't know it,
        check out the exercise list first and look up the id of the exercise you are interested in.
        UNDER NO CIRCUMSTANCES GUESS THE ID, such as 12345. Always use the correct ids.
        You must pass an array of IDs. It can be more than one.
        The following metrics are returned:
        - global_average_score: The average score of all students in the exercise.
        - score_of_student: The score of the student.
        - global_average_latest_submission: The average relative time of the latest
        submissions of all students in the exercise.
        - latest_submission_of_student: The relative time of the latest submission of the student.

        Args:
            exercise_ids (List[int]): List of exercise IDs to fetch metrics for.

        Returns:
            Union[Dict[int, dict], str]: Metrics per exercise ID or error message.
        """
        if not metrics or not metrics.exercise_metrics:
            return "No data available!! Do not requery."
        exercise_metrics = metrics.exercise_metrics
        available_ids = (
            set(exercise_metrics.average_score)
            | set(exercise_metrics.score)
            | set(exercise_metrics.average_latest_submission)
            | set(exercise_metrics.latest_submission)
            | set(exercise_metrics.completed)
        )
        if any(exercise_id in available_ids for exercise_id in exercise_ids):
            return {
                exercise_id: {
                    "global_average_score": exercise_metrics.average_score.get(
                        exercise_id
                    ),
                    "score_of_student": exercise_metrics.score.get(exercise_id, None),
                    "global_average_latest_submission": exercise_metrics.average_latest_submission.get(
                        exercise_id, None
                    ),
                    "latest_submission_of_student": exercise_metrics.latest_submission.get(
                        exercise_id, None
                    ),
                    "completed_by_student": exercise_id in exercise_metrics.completed,
                }
                for exercise_id in exercise_ids
                if exercise_id in available_ids
            }
        else:
            return "No data available! Do not requery."

    return get_student_exercise_metrics
