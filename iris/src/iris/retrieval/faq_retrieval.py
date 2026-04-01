from typing import List

from weaviate import WeaviateClient
from weaviate.collections.classes.filters import Filter

from iris.tracing import observe

from ..common.logging_config import get_logger
from ..common.pipeline_enum import PipelineEnum
from ..common.pyris_message import PyrisMessage
from ..pipeline.prompts.faq_retrieval_prompts import (
    faq_retriever_initial_prompt,
    write_hypothetical_answer_prompt,
)
from ..pipeline.prompts.lecture_retrieval_prompts import (
    rewrite_student_query_prompt,
)
from ..vector_database.faq_schema import FaqSchema, init_faq_schema
from .basic_retrieval import BaseRetrieval, merge_retrieved_chunks

logger = get_logger(__name__)


class FaqRetrieval(BaseRetrieval):
    """FaqRetrieval handles FAQ retrieval operations using a Weaviate client.

    It retrieves FAQ data based on a student's query, processes the results through multiple
    retrieval pipelines (basic and hypothetical), and merges them to return the final FAQ list.
    """

    def __init__(self, client: WeaviateClient, local: bool = False, **kwargs):
        super().__init__(
            client,
            init_faq_schema,
            local=local,
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
        chat_history: list[PyrisMessage],
        student_query: str,
        result_limit: int,
        course_name: str = None,
        course_id: int = None,
        problem_statement: str = None,
        exercise_title: str = None,
        base_url: str = None,
    ) -> List[dict]:
        course_language = self.fetch_course_language(course_id)

        response, response_hyde = self.run_parallel_rewrite_tasks(
            chat_history=chat_history,
            student_query=student_query,
            result_limit=result_limit,
            course_language=course_language,
            initial_prompt=faq_retriever_initial_prompt,
            rewrite_prompt=rewrite_student_query_prompt,
            hypothetical_answer_prompt=write_hypothetical_answer_prompt,
            pipeline_enum=PipelineEnum.IRIS_FAQ_RETRIEVAL_PIPELINE,
            course_name=course_name,
            course_id=course_id,
        )

        basic_retrieved_faqs: list[dict[str, dict]] = [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in response.objects
        ]
        hyde_retrieved_faqs: list[dict[str, dict]] = [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in response_hyde.objects
        ]
        return merge_retrieved_chunks(basic_retrieved_faqs, hyde_retrieved_faqs)

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
