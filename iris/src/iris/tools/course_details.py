"""Tool for retrieving course details."""

from typing import Callable, Optional

from ..domain.data.course_dto import CourseDTO
from ..pipeline.shared.utils import datetime_to_string
from ..web.status.status_update import StatusCallback


def create_tool_get_course_details(
    course: Optional[CourseDTO], callback: StatusCallback
) -> Callable[[], dict]:
    """
    Create a tool that retrieves course details.

    Args:
        course: Course object.
        callback: Callback for status updates.

    Returns:
        Callable[[], dict]: Function that returns course details.
    """

    def get_course_details() -> dict:
        """
        Get the following course details: course name, course description, programming language, course start date,
        and course end date.

        Returns:
            dict: Course name, description, programming language, start and end dates.
        """
        callback.in_progress("Reading course details ...")

        result = {
            "course_name": (
                course.name if (course and course.name) else "No course name provided"
            ),
            "course_description": (
                course.description
                if course and course.description
                else "No course description provided"
            ),
            "programming_language": (
                course.default_programming_language
                if course and course.default_programming_language
                else "No programming language provided"
            ),
            "course_start_date": (
                datetime_to_string(course.start_time)
                if course
                else "No start date provided"
            ),
            "course_end_date": (
                datetime_to_string(course.end_time)
                if course
                else "No end date provided"
            ),
        }

        return result

    return get_course_details
