from typing import List, Optional, Sequence

from weaviate import WeaviateClient
from weaviate.classes.query import Filter, HybridFusion, MetadataQuery

from iris.common.artemis_instance import canonical_artemis_base_url
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
from .course_memory_retrieval_utils import course_memory_scope_filter

logger = get_logger(__name__)


class CourseMemoryRetrieval(BaseRetrieval):
    """Course-scoped hybrid retrieval over verified Q/A pairs.

    Embeds the (optionally rewritten) student question, ranks candidates with a
    ``course_id``-filtered Weaviate hybrid query, and keeps only those that clear
    an absolute cosine-similarity floor (``similarity_threshold``, applied as a
    dense ``near_vector`` certainty gate). Degrades gracefully to an empty result
    if the embedding service is unavailable.
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
            CourseMemorySchema.POST_ID.value,
            CourseMemorySchema.MESSAGE_ID.value,
            CourseMemorySchema.CONVERSATION_ID.value,
            CourseMemorySchema.SOURCE.value,
            CourseMemorySchema.VERIFIED_AT.value,
        ]

    @observe(name="Full Course Memory Retrieval")
    def __call__(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        result_limit: Optional[int] = None,
        *,
        course_id: int,
        base_url: str,
        allowed_conversation_ids: Sequence[int],
        course_name: Optional[str] = None,
        rewrite: bool = True,
    ) -> List[dict]:
        """Retrieve entries that may be served for this run.

        ``allowed_conversation_ids`` lists the channels Artemis considers readable by
        every student of the course at dispatch time. It is required: Iris must never
        cite from a channel that is not, however the entry got stored. An empty list
        returns nothing. ``base_url`` scopes the search to the calling Artemis instance.
        """
        if not course_id or not allowed_conversation_ids:
            return []
        try:
            instance = canonical_artemis_base_url(base_url)
        except ValueError:
            logger.warning("Course memory retrieval without a valid Artemis base URL")
            return []
        allowed = {str(conversation_id) for conversation_id in allowed_conversation_ids}

        config = settings.course_memory
        result_limit = result_limit or config.result_limit
        alpha = config.alpha
        threshold = config.similarity_threshold

        query = student_query
        if rewrite and config.query_rewrite_enabled:
            try:
                # Course memory has no per-course language metadata, and stored
                # questions are embedded in their original language; the rewrite
                # only makes context-poor questions self-contained and MUST NOT
                # translate (see course_memory_query_rewrite_prompt). The unused
                # course_language argument is kept for the shared helper signature.
                query = self.rewrite_student_query(
                    chat_history=chat_history,
                    student_query=student_query,
                    course_language="",
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

        # Course scoping plus the tombstone filter: a retracted thread keeps its
        # object (with deleted=True and its version) so a stale ingestion cannot
        # resurrect it, and that object still sits in the BM25 and vector indexes.
        # Both queries below carry this filter so a tombstone can never be ranked,
        # gated or returned. The filter applies to both the hybrid ranking and the
        # certainty gate.
        course_filter = course_memory_scope_filter(instance, course_id, allowed)
        try:
            vec = self.llm_embedding.embed(query)
            # Rank by hybrid (BM25 + dense). Pin the fusion type so fused scores are
            # deterministic across Weaviate servers (RANKED/RRF would produce scores
            # near ~0.02, silently rejecting everything downstream).
            ranked = self.collection.query.hybrid(
                query=query,
                alpha=alpha,
                vector=vec,
                fusion_type=HybridFusion.RELATIVE_SCORE,
                return_properties=self.get_schema_properties(),
                limit=result_limit,
                filters=course_filter,
            )
            if not ranked.objects:
                return []
            # Relevance gate on ABSOLUTE cosine similarity. Hybrid RELATIVE_SCORE
            # normalises the top hit to 1.0 regardless of true similarity, so it
            # cannot enforce a floor; dense cosine certainty can (design intent:
            # only reuse an answer whose question is genuinely similar).
            # Restricting the gate to the ranked candidates makes it an exact
            # floor: every ranked hit clearing the certainty threshold survives,
            # regardless of how it ranks by pure vector similarity.
            ranked_ids = [obj.uuid for obj in ranked.objects]
            gate = self.collection.query.near_vector(
                near_vector=vec,
                filters=course_filter & Filter.by_id().contains_any(ranked_ids),
                certainty=threshold,
                limit=len(ranked_ids),
                return_metadata=MetadataQuery(certainty=True),
            )
            gate_passed = {obj.uuid for obj in gate.objects}
        except Exception as e:  # noqa: BLE001
            # Graceful degradation: embedding service / Weaviate unavailable.
            logger.warning(
                "Course memory retrieval unavailable, skipping retrieval: %s", e
            )
            return []

        # Keep hybrid-ranked results that clear the cosine-similarity floor. The channel
        # membership is checked again on the returned properties, so a hit can never be
        # served from a channel outside the allowlist, whatever the filter matched.
        return [
            obj.properties
            for obj in ranked.objects
            if obj.uuid in gate_passed
            and str(obj.properties.get(CourseMemorySchema.CONVERSATION_ID.value))
            in allowed
        ]
