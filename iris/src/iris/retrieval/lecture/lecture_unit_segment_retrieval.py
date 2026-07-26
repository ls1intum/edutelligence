from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureUnitRetrievalDTO,
    LectureUnitSegmentRetrievalDTO,
)
from iris.llm import (
    CompletionArguments,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.llm.request_handler.llm_request_handler import (
    LlmRequestHandler,
)
from iris.llm.request_handler.rerank_request_handler import (
    RerankRequestHandler,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.retrieval.lecture.lecture_visibility import (
    is_segment_visible,
    is_unit_released,
)
from iris.tracing import TracedThreadPoolExecutor, observe
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)

logger = get_logger(__name__)


def _coalesce_page_number(display_page_number, page_number) -> int:
    """Return the first known page number, falling back to the -1 sentinel."""
    if display_page_number is not None:
        return display_page_number
    if page_number is not None:
        return page_number
    return -1


class LectureUnitSegmentRetrieval(SubPipeline):
    """LectureUnitSegmentRetrieval retrieves lecture unit segments based on search queries and returns the matching
    results."""

    def __init__(self, client: WeaviateClient, local: bool = False):
        super().__init__(implementation_id="lecture_unit_segment_retrieval_pipeline")
        pipeline_id = "lecture_unit_segment_retrieval_pipeline"
        chat_model = resolve_model(pipeline_id, "default", "chat", local=local)
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=False
        )
        request_handler = LlmRequestHandler(model_id=chat_model)
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.llm_embedding = LlmRequestHandler(embedding_model)
        self.pipeline = self.llm | StrOutputParser()
        self.collection = init_lecture_unit_segment_schema(client)
        self.lecture_unit_collection = init_lecture_unit_schema(client)
        reranker_id = resolve_model(pipeline_id, "default", "reranker", local=False)
        self.cohere_client = RerankRequestHandler(reranker_id)
        self.tokens = []
        # Per-request cache of lecture unit metadata, keyed by
        # (course_id, lecture_id, lecture_unit_id, base_url). Hits from the same unit
        # would otherwise trigger one identical Weaviate lookup each.
        self._lecture_unit_cache: dict = {}

    @observe(name="Lecture Unit Segment Retrieval")
    def __call__(
        self,
        student_query: str,
        rewritten_query: str,
        hypothetical_answer: str,
        lecture_unit_dto: LectureUnitRetrievalDTO,
        result_limit: int = 10,
        hybrid_factor: float = 0.9,
        top_n_reranked_results: int = 7,
        rewritten_query_vector=None,
        hypothetical_answer_vector=None,
    ):
        # The two searches (embed + hybrid search each) are independent;
        # run them concurrently.
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            rewritten_future = executor.submit(
                self.search_in_db,
                lecture_unit_dto,
                rewritten_query,
                hybrid_factor,
                result_limit,
                query_vector=rewritten_query_vector,
            )
            hypothetical_future = executor.submit(
                self.search_in_db,
                lecture_unit_dto,
                hypothetical_answer,
                hybrid_factor,
                result_limit,
                query_vector=hypothetical_answer_vector,
            )
            results_rewritten_query = rewritten_future.result()
            results_hypothetical_answer = hypothetical_future.result()
        unique = {}
        for segment in results_hypothetical_answer + results_rewritten_query:
            unique[segment.uuid] = segment
        results = list(unique.values())
        lecture_unit_segment_retrieval_dtos = []
        for lecture_unit_segment in results:
            lecture_unit_segment_retrieval_dto = self.generate_retrieval_dtos(
                lecture_unit_segment.properties, str(lecture_unit_segment.uuid)
            )
            if lecture_unit_segment_retrieval_dto is None:
                continue

            lecture_unit_segment_retrieval_dtos.append(
                lecture_unit_segment_retrieval_dto
            )

        reranked_answers = self.cohere_client.rerank(
            query=student_query,
            documents=lecture_unit_segment_retrieval_dtos,
            top_n=top_n_reranked_results,
            content_field_name="segment_summary",
        )

        return reranked_answers

    @observe(name="Lecture Unit Segment: Search in DB")
    def search_in_db(
        self,
        lecture_unit_dto: LectureUnitRetrievalDTO,
        query: str,
        hybrid_factor: float,
        result_limit: int,
        query_vector=None,
    ):
        """
        Search the database for the given query.
        """
        logger.info(
            "[LECTURE_UNIT_SEGMENT_RETRIEVAL]: Searching in the database for query: %s",
            query,
        )
        filter_weaviate = None
        if lecture_unit_dto.course_id is not None:
            filter_weaviate = Filter.by_property(
                LectureUnitSegmentSchema.COURSE_ID.value
            ).equal(lecture_unit_dto.course_id)
        if lecture_unit_dto.lecture_id is not None:
            lecture_filter = Filter.by_property(
                LectureUnitSegmentSchema.LECTURE_ID.value
            ).equal(lecture_unit_dto.lecture_id)
            filter_weaviate = (
                filter_weaviate & lecture_filter
                if filter_weaviate is not None
                else lecture_filter
            )
        if lecture_unit_dto.base_url is not None:
            base_url_filter = Filter.by_property(
                LectureUnitSegmentSchema.BASE_URL.value
            ).equal(lecture_unit_dto.base_url)
            filter_weaviate = (
                filter_weaviate & base_url_filter
                if filter_weaviate is not None
                else base_url_filter
            )

        vec = (
            query_vector
            if query_vector is not None
            else self.llm_embedding.embed(query)
        )
        visible_objects = []
        seen_uuids = set()
        offset = 0
        while len(visible_objects) < result_limit and offset < 10_000:
            page_limit = min(result_limit, 10_000 - offset)
            objects = self.collection.query.hybrid(
                query=query,
                alpha=hybrid_factor,
                vector=vec,
                limit=page_limit,
                offset=offset,
                filters=filter_weaviate,
            ).objects
            new_objects = [obj for obj in objects if obj.uuid not in seen_uuids]
            if not new_objects:
                break
            seen_uuids.update(obj.uuid for obj in new_objects)
            visible_objects.extend(
                obj
                for obj in new_objects
                if self.generate_retrieval_dtos(obj.properties, str(obj.uuid))
                is not None
            )
            if len(objects) < page_limit:
                break
            offset += len(objects)
        return visible_objects[:result_limit]

    def generate_retrieval_dtos(self, lecture_unit_segment, uuid: str):
        if not is_segment_visible(lecture_unit_segment):
            return None

        cache_key = (
            lecture_unit_segment[LectureUnitSegmentSchema.COURSE_ID.value],
            lecture_unit_segment[LectureUnitSegmentSchema.LECTURE_ID.value],
            lecture_unit_segment[LectureUnitSegmentSchema.LECTURE_UNIT_ID.value],
            lecture_unit_segment[LectureUnitSegmentSchema.BASE_URL.value],
        )
        if cache_key in self._lecture_unit_cache:
            lecture_unit = self._lecture_unit_cache[cache_key]
        else:
            lecture_unit_filter = Filter.by_property(
                LectureUnitSchema.COURSE_ID.value
            ).equal(lecture_unit_segment[LectureUnitSegmentSchema.COURSE_ID.value])
            lecture_unit_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_ID.value
            ).equal(lecture_unit_segment[LectureUnitSegmentSchema.LECTURE_ID.value])
            lecture_unit_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ).equal(
                lecture_unit_segment[LectureUnitSegmentSchema.LECTURE_UNIT_ID.value]
            )
            lecture_unit_filter &= Filter.by_property(
                LectureUnitSchema.BASE_URL.value
            ).equal(lecture_unit_segment[LectureUnitSegmentSchema.BASE_URL.value])

            lecture_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_unit_filter
            ).objects
            lecture_unit = (
                lecture_units[0].properties if len(lecture_units) > 0 else None
            )
            self._lecture_unit_cache[cache_key] = lecture_unit

        if lecture_unit is None or not is_unit_released(lecture_unit):
            return None
        lecture_unit_segment_retrieval_dto = LectureUnitSegmentRetrievalDTO(
            uuid=uuid,
            course_id=lecture_unit_segment[LectureUnitSegmentSchema.COURSE_ID.value],
            course_name=lecture_unit[LectureUnitSchema.COURSE_NAME.value],
            course_description=lecture_unit[LectureUnitSchema.COURSE_DESCRIPTION.value],
            lecture_id=lecture_unit_segment[LectureUnitSegmentSchema.LECTURE_ID.value],
            lecture_name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
            lecture_unit_id=lecture_unit_segment[
                LectureUnitSegmentSchema.LECTURE_UNIT_ID.value
            ],
            lecture_unit_name=lecture_unit[LectureUnitSchema.LECTURE_UNIT_NAME.value],
            lecture_unit_link=lecture_unit[LectureUnitSchema.LECTURE_UNIT_LINK.value],
            video_link=lecture_unit.get(LectureUnitSchema.VIDEO_LINK.value),
            page_number=lecture_unit_segment[
                LectureUnitSegmentSchema.PAGE_NUMBER.value
            ],
            # Segments ingested before display pages existed carry the property with
            # an explicit None (dict.get's default only covers a MISSING key), and a
            # None must never reach a Weaviate filter (gRPC rejects nil values).
            display_page_number=_coalesce_page_number(
                lecture_unit_segment.get(
                    LectureUnitSegmentSchema.DISPLAY_PAGE_NUMBER.value
                ),
                lecture_unit_segment.get(LectureUnitSegmentSchema.PAGE_NUMBER.value),
            ),
            segment_summary=lecture_unit_segment[
                LectureUnitSegmentSchema.SEGMENT_SUMMARY.value
            ],
            base_url=lecture_unit_segment[LectureUnitSegmentSchema.BASE_URL.value],
        )
        return lecture_unit_segment_retrieval_dto
