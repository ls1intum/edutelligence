from weaviate.collections.classes.filters import Filter

from iris.vector_database.database import VectorDatabase
from iris.vector_database.faq_schema import FaqSchema


def should_allow_faq_tool(db: VectorDatabase, course_id: int) -> bool:
    """
    Checks if there are indexed faqs for the given course

    :param db: The vector database on which the faqs are indexed
    :param course_id: The course ID
    :return: True if there are indexed faqs for the course, False otherwise
    """
    if course_id:
        # Fetch the first object that matches the course ID with the language property
        result = db.faqs.query.fetch_objects(
            filters=Filter.by_property(FaqSchema.COURSE_ID.value).equal(course_id),
            limit=1,
            return_properties=[FaqSchema.COURSE_NAME.value],
        )
        return len(result.objects) > 0
    return False


def format_faqs(retrieved_faqs):
    """
    Formatiert die abgerufenen FAQs in einen String.

    :param retrieved_faqs: Liste der abgerufenen FAQs
    :return: Formatierter String mit den FAQ-Daten
    """
    result = ""
    for faq in retrieved_faqs:
        res = (
            f"[FAQ ID: {faq.get(FaqSchema.FAQ_ID.value)}, FAQ Question: {faq.get(FaqSchema.QUESTION_TITLE.value)},"
            f" FAQ Answer: {faq.get(FaqSchema.QUESTION_ANSWER.value)}]"
        )
        result += res
    return result
