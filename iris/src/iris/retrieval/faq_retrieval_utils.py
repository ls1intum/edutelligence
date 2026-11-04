from typing import Callable, Optional

from weaviate.collections.classes.filters import Filter

from iris.common.logging_config import get_logger
from iris.vector_database.database import VectorDatabase
from iris.vector_database.faq_schema import FaqSchema

logger = get_logger(__name__)

# Pages read at most while rows of other instances are dropped. With a field-tokenized base_url the
# Weaviate filter is exact, nothing is dropped and the first page is the answer.
_MAX_PAGES = 5


def faq_instance_filter(course_id: int, base_url: str) -> Filter:
    """The FAQ rows of one course on one Artemis instance.

    The equality on base_url is exact only with field tokenization; with the word tokenization that
    auto-schema can create, it also matches a URL that contains all words of this one, so the rows
    must still be checked with :func:`fetch_owned_faqs`.
    """
    return Filter.by_property(FaqSchema.COURSE_ID.value).equal(
        course_id
    ) & Filter.by_property(FaqSchema.BASE_URL.value).equal(base_url)


def fetch_owned_faqs(
    fetch_page: Callable[[int, int], list], base_url: str, limit: int
) -> tuple[list, bool]:
    """The first ``limit`` rows that belong to the Artemis instance at ``base_url``, in result order.

    ``fetch_page(offset, limit)`` returns one page of Weaviate objects filtered by
    :func:`faq_instance_filter`, with base_url among their properties. Rows of another instance are
    dropped and the next page is read, so they cannot push this instance's FAQs out of the result.
    Legacy rows without a base URL never match: their instance is unknown, and the FAQ census makes
    Artemis push those FAQs again, which replaces them.

    :return: the owned rows, and whether the scan stopped at its page budget with ``limit`` not
        reached and more rows left, so that further owned rows may exist
    """
    owned = []
    dropped = 0
    budget_spent = False
    for page in range(_MAX_PAGES):
        objects = fetch_page(page * limit, limit)
        for obj in objects:
            if obj.properties.get(FaqSchema.BASE_URL.value) == base_url:
                owned.append(obj)
            else:
                dropped += 1
        if len(owned) >= limit or len(objects) < limit:
            break
    else:
        budget_spent = True
    if dropped:
        logger.warning(
            "Dropped %d FAQ row(s) of other Artemis instances that the base URL filter matched; "
            "%s.%s is not field-tokenized",
            dropped,
            FaqSchema.COLLECTION_NAME.value,
            FaqSchema.BASE_URL.value,
        )
    return owned[:limit], budget_spent


def should_allow_faq_tool(
    db: VectorDatabase, course_id: int, base_url: Optional[str]
) -> bool:
    """
    Check if there are indexed FAQs for the given course on the given Artemis instance.

    Args:
        db (VectorDatabase): The vector database instance.
        course_id (int): The course ID.
        base_url (Optional[str]): The base URL of the asking Artemis instance; without one no FAQ
            is allowed, since it is unknown which instance's FAQs the course would see.

    Returns:
        bool: True if there are indexed FAQs for the course, False otherwise, also when Weaviate is
        unavailable, so the chat still answers without the FAQ tool.
    """
    if not course_id or not base_url:
        return False
    filters = faq_instance_filter(course_id, base_url)
    try:
        owned, budget_spent = fetch_owned_faqs(
            lambda offset, limit: db.faqs.query.fetch_objects(
                filters=filters,
                limit=limit,
                offset=offset,
                return_properties=[FaqSchema.BASE_URL.value],
            ).objects,
            base_url,
            1,
        )
    except Exception:
        logger.warning(
            "Weaviate is unavailable; answering without the FAQ tool | course_id=%s",
            course_id,
            exc_info=True,
        )
        return False
    # A scan that ran out of pages may have missed an owned row; the tool then stays on, since the
    # retrieval itself still returns only owned rows
    return len(owned) > 0 or budget_spent


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
