from weaviate.collections.classes.filters import Filter

from iris.common.logging_config import get_logger
from iris.vector_database.database import VectorDatabase
from iris.vector_database.faq_schema import FaqSchema

logger = get_logger(__name__)


def should_allow_faq_tool(db: VectorDatabase, course_id: int) -> bool:
    """
    Check if there are indexed FAQs for the given course.

    Args:
        db (VectorDatabase): The vector database instance.
        course_id (int): The course ID.

    Returns:
        bool: True if there are indexed FAQs for the course, False otherwise, also when Weaviate is
        unavailable, so the chat still answers without the FAQ tool.
    """
    if not course_id:
        return False
    try:
        # Fetch the first object that matches the course ID with the language property
        result = db.faqs.query.fetch_objects(
            filters=Filter.by_property(FaqSchema.COURSE_ID.value).equal(course_id),
            limit=1,
            return_properties=[FaqSchema.COURSE_NAME.value],
        )
    except Exception:
        logger.warning(
            "Weaviate is unavailable; answering without the FAQ tool | course_id=%s",
            course_id,
            exc_info=True,
        )
        return False
    return len(result.objects) > 0


def format_faqs(retrieved_faqs):
    """
    Format retrieved FAQs into a string.

    Args:
        retrieved_faqs (List[dict]): List of retrieved FAQs.

    Returns:
        str: Formatted FAQ string.
    """
    result = ""
    for faq in retrieved_faqs:
        res = (
            f"[FAQ ID: {faq.get(FaqSchema.FAQ_ID.value)}, FAQ Question: {faq.get(FaqSchema.QUESTION_TITLE.value)},"
            f" FAQ Answer: {faq.get(FaqSchema.QUESTION_ANSWER.value)}]"
        )
        result += res
    return result
