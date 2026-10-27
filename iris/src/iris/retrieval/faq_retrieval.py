from typing import List

from weaviate import WeaviateClient
from weaviate.collections.classes.filters import Filter

from iris.tracing import observe

from ..common.logging_config import get_logger
from ..vector_database.faq_schema import FaqSchema, init_faq_schema
from .basic_retrieval import BaseRetrieval

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
        ]

    @observe(name="Full Faq Retrieval")
    def __call__(
        self,
        search_query: str,
        course_id: int,
        result_limit: int = 10,
    ) -> List[dict]:
        """Search the course's FAQs for a query the agent wrote itself."""
        response = self.search_in_db(
            query=search_query,
            hybrid_factor=0.9,
            result_limit=result_limit,
            schema_properties=self.get_schema_properties(),
            course_id=course_id,
        )
        return [obj.properties for obj in response.objects]

    @observe(name="FAQ: Search in DB")
    def get_faqs_from_db(
        self,
        course_id: int,
        search_text: str = None,
        result_limit: int = 10,
        hybrid_factor: float = 0.75,
    ) -> List[dict]:
        """
        Retrieves FAQs from the database, optionally with a similarity search on question_title and question_answer.

        :param course_id: ID of the course to fetch FAQs for a specific course.
        :param search_text: Optional search text used for semantic search.
        :param result_limit: Number of FAQs to return.
        :param hybrid_factor: Weighting between vector-based and keyword-based results.
        :return: List of retrieved FAQs.
        """
        filter_weaviate = Filter.by_property("course_id").equal(course_id)

        if search_text:
            vec = self.llm_embedding.embed(search_text)

            response = self.collection.query.hybrid(
                query=search_text,
                vector=vec,
                alpha=hybrid_factor,
                return_properties=self.get_schema_properties(),
                limit=result_limit,
                filters=filter_weaviate,
            )
        else:

            response = self.collection.query.fetch_objects(
                filters=filter_weaviate,
                limit=result_limit,
                return_properties=self.get_schema_properties(),
            )

        faqs = [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in response.objects
        ]
        return faqs
