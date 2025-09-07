from typing import Callable

from iris.domain.data.course_dto import CourseDTO
from iris.web.status.status_update import StatusCallback


def create_tool_get_simple_course_details(
    dto: CourseDTO, callback: StatusCallback
) -> Callable[[], dict]:
    """
    Create a tool that retrieves simple course details.
    Args:
        dto (CourseDTO): DTO containing course data.
        callback (StatusCallback): Callback for status updates.
    Returns:
        Callable[[], dict]: Function that returns course details.
    """

    def get_simple_course_details() -> dict:
        """
        Get the following course details: course name, course description, programming language, course start date,
        and course end date.
        Returns:
            dict: Course name, description, programming language, start and end dates.
        """
        callback.in_progress("Reading simple course details ...")
        return {
            "course_name": dto.name or "No course provided",
            "course_description": dto.description or "No course description provided",
        }

    return get_simple_course_details
