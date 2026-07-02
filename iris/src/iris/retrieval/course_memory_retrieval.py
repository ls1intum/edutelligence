from typing import List, Optional

from weaviate import WeaviateClient
from weaviate.classes.query import Filter, MetadataQuery

from iris.config import settings
from iris.tracing import observe

from ..common.logging_config import get_logger
from ..common.pipeline_enum import PipelineEnum
from ..common.pyris_message import PyrisMessage
from ..pipeline.prompts.course_memory_prompts import (
    course_memory_query_rewrite_initial_prompt,
    course_memory_query_rewrite_prompt,
)
from ..vector_database.course_memory_schema import (
    CourseMemorySchema,
    init_course_memory_schema,
)
from .basic_retrieval import BaseRetrieval

logger = get_logger(__name__)


class CourseMemoryRetrieval(BaseRetrieval):
    """Course-scoped hybrid retrieval over verified Q/A pairs.

    Embeds the (optionally rewritten) student question, runs a single Weaviate
    hybrid query filtered by ``course_id``, and keeps only results whose fused
    score meets the configured similarity threshold. Degrades gracefully to an
    empty result if the embedding service is unavailable.
    """

    def __init__(self, client: WeaviateClient, local: bool = False, **kwargs):
        super().__init__(
            client,
            init_course_memory_schema,
            local=local,
            implementation_id="course_memory_retrieval_pipeline",
        )

    def get_schema_properties(self) -> List[str]:
        return [
            CourseMemorySchema.QUESTION.value,
            CourseMemorySchema.ANSWER.value,
            CourseMemorySchema.COURSE_ID.value,
            CourseMemorySchema.MESSAGE_ID.value,
            CourseMemorySchema.CONVERSATION_ID.value,
            CourseMemorySchema.SOURCE.value,
            CourseMemorySchema.VERIFIED_AT.value,
            CourseMemorySchema.VERIFIED_BY.value,
        ]

    @observe(name="Full Course Memory Retrieval")
    def __call__(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        result_limit: Optional[int] = None,
        course_id: Optional[int] = None,
        course_name: Optional[str] = None,
        base_url: Optional[str] = None,
        rewrite: bool = True,
    ) -> List[dict]:
        # Course scoping is mandatory.
        if not course_id:
            return []

        config = settings.course_memory
        result_limit = result_limit or config.result_limit
        alpha = config.alpha
        threshold = config.similarity_threshold

        query = student_query
        if rewrite and config.query_rewrite_enabled:
            try:
                course_language = self.fetch_course_language(course_id)
                query = self.rewrite_student_query(
                    chat_history=chat_history,
                    student_query=student_query,
                    course_language=course_language,
                    course_name=course_name or "the course",
                    initial_prompt=course_memory_query_rewrite_initial_prompt,
                    rewrite_prompt=course_memory_query_rewrite_prompt,
                    pipeline_enum=PipelineEnum.IRIS_COURSE_MEMORY_RETRIEVAL_PIPELINE,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Course memory query rewrite failed, using raw query: %s", e
                )
                query = student_query

        try:
            vec = self.llm_embedding.embed(query)
            response = self.collection.query.hybrid(
                query=query,
                alpha=alpha,
                vector=vec,
                return_properties=self.get_schema_properties(),
                limit=result_limit,
                filters=Filter.by_property(CourseMemorySchema.COURSE_ID.value).equal(
                    course_id
                ),
                return_metadata=MetadataQuery(score=True),
            )
        except Exception as e:  # noqa: BLE001
            # Graceful degradation: embedding service / Weaviate unavailable.
            logger.warning(
                "Course memory retrieval unavailable, skipping retrieval: %s", e
            )
            return []

        # Filter on the hybrid (RRF) fused score. NOTE: this is not a raw cosine
        # similarity; the 0.85 default is a starting value pending empirical
        # calibration (out of scope per spec).
        results: List[dict] = []
        for obj in response.objects:
            score = (
                obj.metadata.score
                if obj.metadata and obj.metadata.score is not None
                else 0.0
            )
            if score >= threshold:
                results.append(obj.properties)
        return results
