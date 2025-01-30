import logging
from typing import List
from langsmith import traceable
from weaviate import WeaviateClient
from app.common.PipelineEnum import PipelineEnum
from .basic_retrieval import BaseRetrieval, merge_retrieved_chunks
from ..common.pyris_message import PyrisMessage
from ..pipeline.prompts.faq_retrieval_prompts import (
    faq_retriever_initial_prompt,
    write_hypothetical_answer_prompt,
)
from ..pipeline.prompts.lecture_retrieval_prompts import (
    rewrite_student_query_prompt,
)
from ..vector_database.faq_schema import FaqSchema, init_faq_schema

logger = logging.getLogger(__name__)


class FaqRetrieval(BaseRetrieval):
    def __init__(self, client: WeaviateClient, **kwargs):
        super().__init__(
            client, init_faq_schema, implementation_id="faq_retrieval_pipeline"
        )

    def get_schema_properties(self) -> List[str]:
        return [
            FaqSchema.COURSE_ID.value,
            FaqSchema.FAQ_ID.value,
            FaqSchema.QUESTION_TITLE.value,
            FaqSchema.QUESTION_ANSWER.value,
        ]

    @traceable(name="Full Faq Retrieval")
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
