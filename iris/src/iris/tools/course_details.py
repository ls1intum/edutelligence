"""Tool for retrieving course details."""

from typing import Callable, Optional, Union

from ..domain.data.course_dto import CourseDTO
from ..domain.data.extended_course_dto import ExtendedCourseDTO
from ..pipeline.shared.utils import datetime_to_string
from ..web.status.status_update import StatusCallback


def create_tool_get_course_details(
    course: Optional[Union[CourseDTO, ExtendedCourseDTO]], callback: StatusCallback
) -> Callable[[], dict]:
    """
    Create a tool that retrieves course details.

    Args:
        course: Course object (CourseDTO or ExtendedCourseDTO).
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

        # ExtendedCourseDTO has more fields than CourseDTO
        result = {
            "course_name": (
                course.name if (course and course.name) else "No course name provided"
            ),
            "course_description": (
                course.description
                if course and course.description
                else "No course description provided"
            ),
        }

        # Only ExtendedCourseDTO has these fields
        if isinstance(course, ExtendedCourseDTO):
            result["programming_language"] = (
                course.default_programming_language
                if course.default_programming_language
                else "No programming language provided"
            )
            result["course_start_date"] = datetime_to_string(course.start_time)
            result["course_end_date"] = datetime_to_string(course.end_time)
        else:
            # CourseDTO doesn't have these fields
            result["programming_language"] = "No programming language provided"
            result["course_start_date"] = "No start date provided"
            result["course_end_date"] = "No end date provided"

        return result

    return get_course_details
