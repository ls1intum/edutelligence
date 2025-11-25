"""Tool for retrieving the competency list."""

from typing import Callable, List, Optional

from ..common.mastery_utils import get_mastery
from ..domain.data.competency_dto import CompetencyDTO
from ..domain.data.metrics.student_metrics_dto import StudentMetricsDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_competency_list(
    competencies: Optional[List[CompetencyDTO]],
    metrics: Optional[StudentMetricsDTO],
    callback: StatusCallback,
) -> Callable[[], List]:
    """
    Create a tool that retrieves the competency list.

    Args:
        competencies: List of competencies.
        metrics: Student metrics data.
        callback: Callback for status updates.

    Returns:
        Callable[[], List]: Function that returns competencies with metrics.
    """

    def get_competency_list() -> list:
        """
        Get the list of competencies in the course.
        Exercises might be associated with competencies. A competency is a skill or knowledge that a student
        should have after completing the course, and instructors may add lectures and exercises
        to these competencies.
        You can use this if the students asks you about a competency, or if you want to provide additional context
        regarding their progress overall or in a specific area.
        A competency has the following attributes: name, description, taxonomy, soft due date, optional,
        and mastery threshold.
        The response may include metrics for each competency, such as progress and mastery (0% - 100%).
        These are system-generated.
        The judgment of learning (JOL) values indicate the self-reported mastery by the student (0 - 5, 5 star).
        The object describing it also indicates the system-computed mastery at the time when the student
        added their JoL assessment.

        Returns:
            list: Competencies with info, exercise IDs, progress, mastery, and JOL.
        """
        callback.in_progress("Reading competency list ...")
        if not competencies:
            return []

        if not metrics or not metrics.competency_metrics:
            return [
                {
                    "info": (
                        comp.model_dump()
                        if hasattr(comp, "model_dump")
                        else comp.dict()
                    ),
                    "exercise_ids": [],
                    "progress": 0,
                    "mastery": 0,
                    "judgment_of_learning": None,
                }
                for comp in competencies
            ]

        competency_metrics = metrics.competency_metrics
        return [
            {
                "info": competency_metrics.competency_information.get(comp, None),
                "exercise_ids": competency_metrics.exercises.get(comp, []),
                "progress": competency_metrics.progress.get(comp, 0),
                "mastery": get_mastery(
                    competency_metrics.progress.get(comp, 0),
                    competency_metrics.confidence.get(comp, 0),
                ),
                "judgment_of_learning": (
                    jol.json()
                    if competency_metrics.jol_values
                    and (jol := competency_metrics.jol_values.get(comp)) is not None
                    else None
                ),
            }
            for comp in competency_metrics.competency_information
        ]

    return get_competency_list
