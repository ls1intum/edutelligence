from weaviate.collections.classes.filters import Filter

from iris.pipeline.shared.citation_registry import CITE_TYPE_FAQ
from iris.vector_database.database import VectorDatabase
from iris.vector_database.faq_schema import FaqSchema


def should_allow_faq_tool(db: VectorDatabase, course_id: int) -> bool:
    """
    Check if there are indexed FAQs for the given course.

    Args:
        db (VectorDatabase): The vector database instance.
        course_id (int): The course ID.

    Returns:
        bool: True if there are indexed FAQs for the course, False otherwise.
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


def format_faqs(retrieved_faqs, citation_registry=None):
    """
    Format retrieved FAQs into a string.

    Args:
        retrieved_faqs (List[dict]): List of retrieved FAQs.
        citation_registry: If given, each FAQ is registered and its citation
            handle is shown to the model so it can cite inline. Callers that do
            not cite pass ``None``.

    Returns:
        str: Formatted FAQ string.
    """
    result = ""
    for faq in retrieved_faqs:
        faq_id = faq.get(FaqSchema.FAQ_ID.value)
        question = faq.get(FaqSchema.QUESTION_TITLE.value)
        answer = faq.get(FaqSchema.QUESTION_ANSWER.value)
        res = f"[FAQ ID: {faq_id}, FAQ Question: {question}," f" FAQ Answer: {answer}]"
        if citation_registry is not None:
            content = " ".join(part for part in (question, answer) if part).strip()
            if content:
                # Appended after the FAQ block so the handle's own brackets do
                # not nest inside it.
                handle = citation_registry.register(
                    CITE_TYPE_FAQ, faq_id, content, dedup_key=f"faq:{faq_id}"
                )
                res += f" Citation id: {handle}"
        result += res
    return result
