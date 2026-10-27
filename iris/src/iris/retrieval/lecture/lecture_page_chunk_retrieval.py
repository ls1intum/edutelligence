from typing import List

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureUnitPageChunkRetrievalDTO,
    LectureUnitRetrievalDTO,
)
from iris.llm import LlmRequestHandler
from iris.llm.llm_configuration import resolve_model
from iris.llm.request_handler.rerank_request_handler import (
    RerankRequestHandler,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.retrieval.lecture.lecture_visibility import (
    is_slide_visible,
    is_unit_released,
)
from iris.tracing import observe
from iris.vector_database.instance_filter import artemis_instance_filter
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)

logger = get_logger(__name__)


class LecturePageChunkRetrieval(SubPipeline):
    """
    Class for retrieving lecture data from the database.
    """

    tokens: List[TokenUsageDTO]

    def __init__(self, client: WeaviateClient):
        super().__init__(implementation_id="lecture_retrieval_pipeline")
        pipeline_id = "lecture_retrieval_pipeline"
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=False
        )
        self.llm_embedding = LlmRequestHandler(embedding_model)
        reranker_id = resolve_model(pipeline_id, "default", "reranker", local=False)
        self.cohere_client = RerankRequestHandler(reranker_id)
        self.lecture_unit_page_chunk_collection = init_lecture_unit_page_chunk_schema(
            client
        )
        self.lecture_unit_collection = init_lecture_unit_schema(client)

        self.tokens = []
        # Per-request cache of lecture unit metadata, keyed by
        # (course_id, lecture_id, lecture_unit_id, base_url). Hits from the
        # same unit would otherwise trigger one identical Weaviate lookup each.
        self._lecture_unit_cache: dict = {}

    @observe(name="Full Lecture Retrieval")
    def __call__(
        self,
        query: str,
        lecture_unit: LectureUnitRetrievalDTO,
        result_limit: int = 10,
        hybrid_factor: float = 0.9,
        top_n_reranked_results: int = 7,
        query_vector=None,
    ) -> list[LectureUnitPageChunkRetrievalDTO]:
        """
        Search the lecture unit's slide chunks for the query and rerank them against it.
        """
        results = self.search_in_db(
            query=query,
            hybrid_factor=hybrid_factor,
            result_limit=result_limit,
            lecture_unit_dto=lecture_unit,
            query_vector=query_vector,
        )

        page_chunks = [
            dto
            for chunk in results
            if (dto := self.generate_retrieval_dtos(chunk.properties, str(chunk.uuid)))
            is not None
        ]

        return self.cohere_client.rerank(
            query,
            page_chunks,
            top_n_reranked_results,
            "page_text_content",
        )

    @observe(name="Retrieval: Search in DB")
    def search_in_db(
        self,
        query: str,
        hybrid_factor: float,
        result_limit: int,
        lecture_unit_dto: LectureUnitRetrievalDTO,
        query_vector=None,
    ):
        """
        Search the database for the given query.
        """
        logger.info(
            "[PAGE_CHUNK_RETRIEVAL] Searching in the database for query: %s", query
        )
        filter_weaviate = None
        if lecture_unit_dto.course_id is not None:
            filter_weaviate = Filter.by_property(
                LectureUnitPageChunkSchema.COURSE_ID.value
            ).equal(lecture_unit_dto.course_id)
        if lecture_unit_dto.lecture_id is not None:
            lecture_filter = Filter.by_property(
                LectureUnitPageChunkSchema.LECTURE_ID.value
            ).equal(lecture_unit_dto.lecture_id)
            filter_weaviate = (
                lecture_filter
                if filter_weaviate is None
                else filter_weaviate & lecture_filter
            )
        if getattr(lecture_unit_dto, "lecture_unit_id", None) is not None:
            lecture_unit_filter = Filter.by_property(
                LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
            ).equal(lecture_unit_dto.lecture_unit_id)
            filter_weaviate = (
                lecture_unit_filter
                if filter_weaviate is None
                else filter_weaviate & lecture_unit_filter
            )
        if lecture_unit_dto.base_url is not None:
            base_url_filter = artemis_instance_filter(
                LectureUnitPageChunkSchema, lecture_unit_dto.base_url
            )
            filter_weaviate = (
                base_url_filter
                if filter_weaviate is None
                else filter_weaviate & base_url_filter
            )

        vec = (
            query_vector
            if query_vector is not None
            else self.llm_embedding.embed(query)
        )
        visible_objects = []
        seen_uuids = set()
        offset = 0
        max_candidates = 10_000
        while len(visible_objects) < result_limit and offset < max_candidates:
            page_limit = min(result_limit, max_candidates - offset)
            objects = self.lecture_unit_page_chunk_collection.query.hybrid(
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

    def generate_retrieval_dtos(self, lecture_page_chunk, uuid):
        if not is_slide_visible(lecture_page_chunk):
            return None

        cache_key = (
            lecture_page_chunk[LectureUnitPageChunkSchema.COURSE_ID.value],
            lecture_page_chunk[LectureUnitPageChunkSchema.LECTURE_ID.value],
            lecture_page_chunk[LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value],
            lecture_page_chunk[LectureUnitPageChunkSchema.BASE_URL.value],
        )
        if cache_key in self._lecture_unit_cache:
            lecture_unit = self._lecture_unit_cache[cache_key]
        else:
            lecture_unit_filter = Filter.by_property(
                LectureUnitSchema.COURSE_ID.value
            ).equal(lecture_page_chunk[LectureUnitPageChunkSchema.COURSE_ID.value])
            lecture_unit_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_ID.value
            ).equal(lecture_page_chunk[LectureUnitPageChunkSchema.LECTURE_ID.value])
            lecture_unit_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ).equal(
                lecture_page_chunk[LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value]
            )
            lecture_unit_filter &= artemis_instance_filter(
                LectureUnitSchema,
                lecture_page_chunk[LectureUnitPageChunkSchema.BASE_URL.value],
            )

            lecture_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_unit_filter
            ).objects
            lecture_unit = (
                lecture_units[0].properties if len(lecture_units) > 0 else None
            )
            self._lecture_unit_cache[cache_key] = lecture_unit

        if lecture_unit is None or not is_unit_released(lecture_unit):
            return None
        else:
            lecture_transcription_dto = LectureUnitPageChunkRetrievalDTO(
                uuid=uuid,
                course_id=lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name=lecture_unit[LectureUnitSchema.COURSE_NAME.value],
                course_description=lecture_unit[
                    LectureUnitSchema.COURSE_DESCRIPTION.value
                ],
                lecture_id=lecture_page_chunk[
                    LectureUnitPageChunkSchema.LECTURE_ID.value
                ],
                lecture_name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
                lecture_unit_id=lecture_page_chunk[
                    LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
                ],
                lecture_unit_name=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_NAME.value
                ],
                lecture_unit_link=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_LINK.value
                ],
                course_language=lecture_page_chunk[
                    LectureUnitPageChunkSchema.COURSE_LANGUAGE.value
                ],
                page_number=lecture_page_chunk[
                    LectureUnitPageChunkSchema.PAGE_NUMBER.value
                ],
                display_page_number=lecture_page_chunk.get(
                    LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
                    lecture_page_chunk[LectureUnitPageChunkSchema.PAGE_NUMBER.value],
                ),
                page_text_content=lecture_page_chunk[
                    LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value
                ],
                base_url=lecture_page_chunk[LectureUnitPageChunkSchema.BASE_URL.value],
            )
            return lecture_transcription_dto
