from weaviate.collections.classes.filters import Filter

from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_unit_schema import LectureUnitSchema


def should_allow_lecture_tool(db: VectorDatabase, course_id: int) -> bool:
    """
    Check if there are indexed lectures for the given course.

    Args:
        db (VectorDatabase): The vector database instance.
        course_id (int): The course ID.

    Returns:
        bool: True if there are indexed lectures for the course, False otherwise.
    """

    if not course_id:
        return False
    # Fetch the first object that matches the course ID with the language property
    result = db.lecture_units.query.fetch_objects(
        filters=Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(course_id),
        limit=1,
        return_properties=[
            LectureUnitSchema.COURSE_NAME.value
        ],  # Requesting a minimal property
    )
    return len(result.objects) > 0
