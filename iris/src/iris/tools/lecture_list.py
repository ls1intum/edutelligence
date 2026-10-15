"""Tool that lists the lectures of the course together with their IDs.

Lecture content retrieval stays scoped to the active lecture and reports
lecture names only, so it cannot supply the ID a context switch needs. This
tool provides the course-wide name to ID mapping instead.
"""

from typing import Callable, List, Optional

from ..domain.data.lecture_dto import PyrisLectureDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_lecture_list(
    lectures: Optional[List[PyrisLectureDTO]], callback: StatusCallback
) -> Callable[[], List[dict]]:
    """
    Create a tool that lists the lectures of the course.

    Args:
        lectures: Lectures of the course as sent by Artemis.
        callback: Callback for status updates.

    Returns:
        Callable[[], List[dict]]: Function that returns the list of lectures.
    """
    del callback

    def get_lecture_list() -> list[dict]:
        """
        Get the list of lectures in the course, each with its lecture ID, its
        name and the names of its lecture units.
        Use this to find the ID of a lecture, for example before switching the
        chat context to another lecture. Lecture content retrieval only returns
        content of the currently active lecture and never returns lecture IDs,
        so this is the only way to identify another lecture.
        The list covers every lecture of the course; lecture units that are not
        yet released to students are omitted.

        Returns:
            list[dict]: Lecture ID, lecture name and lecture unit names per lecture.
        """
        return [
            {
                "lecture_id": lecture.id,
                "lecture_name": lecture.title,
                "lecture_unit_names": [unit.name for unit in lecture.units],
            }
            for lecture in lectures or []
        ]

    return get_lecture_list
