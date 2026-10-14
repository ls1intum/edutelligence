from weaviate.collections.classes.filters import Filter

from ...common.logging_config import get_logger
from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_unit_schema import LectureUnitSchema

logger = get_logger(__name__)


def should_allow_lecture_tool(db: VectorDatabase, course_id: int) -> bool:
    """
    Check if there are indexed lectures for the given course.

    Args:
        db (VectorDatabase): The vector database instance.
        course_id (int): The course ID.

    Returns:
        bool: True if there are indexed lectures for the course, False otherwise, also when Weaviate is
        unavailable, so the chat still answers without the lecture tool.
    """

    if not course_id:
        return False
    try:
        # Fetch the first object that matches the course ID with the language property
        result = db.lecture_units.query.fetch_objects(
            filters=Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                course_id
            ),
            limit=1,
            return_properties=[
                LectureUnitSchema.COURSE_NAME.value
            ],  # Requesting a minimal property
        )
    except Exception:
        logger.warning(
            "Weaviate is unavailable; answering without the lecture tool | course_id=%s",
            course_id,
            exc_info=True,
        )
        return False
    return len(result.objects) > 0
