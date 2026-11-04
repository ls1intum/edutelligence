from typing import List, Optional

from weaviate import WeaviateClient

from iris.tracing import observe

from ..common.logging_config import get_logger
from ..vector_database.faq_schema import FaqSchema, init_faq_schema
from .basic_retrieval import BaseRetrieval
from .faq_retrieval_utils import faq_instance_filter, fetch_owned_faqs

logger = get_logger(__name__)


class FaqRetrieval(BaseRetrieval):
    """FaqRetrieval handles FAQ retrieval operations using a Weaviate client.

    It searches the FAQs of a course for a query the agent wrote, and the FAQ
    consistency check of the rewriting pipeline reads FAQs through it.
    """

    def __init__(self, client: WeaviateClient, **kwargs):
        super().__init__(
            client,
            init_faq_schema,
            implementation_id="faq_retrieval_pipeline",
        )

    def get_schema_properties(self) -> List[str]:
        return [
            FaqSchema.COURSE_ID.value,
            FaqSchema.FAQ_ID.value,
            FaqSchema.QUESTION_TITLE.value,
            FaqSchema.QUESTION_ANSWER.value,
            FaqSchema.BASE_URL.value,
        ]

    @observe(name="Full Faq Retrieval")
    def __call__(
        self,
        search_query: str,
        course_id: int,
        base_url: Optional[str],
        result_limit: int = 10,
    ) -> List[dict]:
        """Search the course's FAQs on this Artemis instance for a query the agent wrote itself."""
        return [
            obj.properties
            for obj in self._owned_faqs(
                course_id, base_url, search_query, result_limit, hybrid_factor=0.9
            )
        ]

    @observe(name="FAQ: Search in DB")
    def get_faqs_from_db(
        self,
        course_id: int,
        base_url: Optional[str],
        search_text: str = None,
        result_limit: int = 10,
        hybrid_factor: float = 0.75,
    ) -> List[dict]:
        """
        Retrieves FAQs from the database, optionally with a similarity search on question_title and question_answer.

        :param course_id: ID of the course to fetch FAQs for a specific course.
        :param base_url: Base URL of the Artemis instance the course belongs to; without one no FAQ is returned.
        :param search_text: Optional search text used for semantic search.
        :param result_limit: Number of FAQs to return.
        :param hybrid_factor: Weighting between vector-based and keyword-based results.
        :return: List of retrieved FAQs.
        """
        return [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in self._owned_faqs(
                course_id, base_url, search_text, result_limit, hybrid_factor
            )
        ]

    def _owned_faqs(
        self,
        course_id: int,
        base_url: Optional[str],
        search_text: Optional[str],
        result_limit: int,
        hybrid_factor: float,
    ) -> list:
        """The course's FAQ rows of the Artemis instance at ``base_url``, best match first.

        Another instance may use the same course id, so the course id alone does not identify the
        course. Without a base URL nothing is returned.
        """
        if not base_url:
            return []
        filters = faq_instance_filter(course_id, base_url)
        properties = self.get_schema_properties()
        if search_text:
            vector = self.llm_embedding.embed(search_text)

            def fetch_page(offset: int, limit: int) -> list:
                return self.collection.query.hybrid(
                    query=search_text,
                    vector=vector,
                    alpha=hybrid_factor,
                    return_properties=properties,
                    limit=limit,
                    offset=offset,
                    filters=filters,
                ).objects

        else:

            def fetch_page(offset: int, limit: int) -> list:
                return self.collection.query.fetch_objects(
                    filters=filters,
                    limit=limit,
                    offset=offset,
                    return_properties=properties,
                ).objects

        return fetch_owned_faqs(fetch_page, base_url, result_limit)[0]
