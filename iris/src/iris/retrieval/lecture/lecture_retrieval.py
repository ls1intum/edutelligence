from typing import Any, Dict, List, Optional

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.common.timing import timed_span
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
    LectureUnitRetrievalDTO,
    LectureUnitSegmentRetrievalDTO,
)
from iris.llm.llm_configuration import LlmConfigurationError, resolve_model
from iris.llm.request_handler.llm_request_handler import (
    LlmRequestHandler,
)
from iris.llm.request_handler.rerank_request_handler import (
    RerankRequestHandler,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.retrieval.lecture.lecture_page_chunk_retrieval import (
    LecturePageChunkRetrieval,
)
from iris.retrieval.lecture.lecture_transcription_retrieval import (
    LectureTranscriptionRetrieval,
)
from iris.retrieval.lecture.lecture_unit_segment_retrieval import (
    LectureUnitSegmentRetrieval,
)
from iris.retrieval.lecture.lecture_visibility import (
    is_slide_visible,
    is_unit_released,
)
from iris.tracing import TracedThreadPoolExecutor, observe
from iris.vector_database.instance_filter import artemis_instance_filter
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)

logger = get_logger(__name__)


class LectureRetrieval(SubPipeline):
    """LectureRetrieval retrieves lecture data from the vector database by processing lecture units, transcriptions,
     and page chunks.

    It combines various sources of lecture-related data and formats them into a single DTO for further processing.
    """

    def __init__(self, client: WeaviateClient):
        super().__init__(implementation_id="lecture_retrieval_pipeline")
        pipeline_id = "lecture_retrieval_pipeline"
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=False
        )
        self.llm_embedding = LlmRequestHandler(embedding_model)

        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.lecture_transcription_collection = init_lecture_transcription_schema(
            client
        )
        self.lecture_unit_page_chunk_collection = init_lecture_unit_page_chunk_schema(
            client
        )

        self.tokens = []
        self._transcription_presence_cache: dict = {}
        self._release_cache: dict[tuple[int, int, Optional[str]], bool] = {}

        self.lecture_unit_segment_pipeline = LectureUnitSegmentRetrieval(client)
        self.lecture_transcription_pipeline = LectureTranscriptionRetrieval(client)
        self.lecture_unit_page_chunk_pipeline = LecturePageChunkRetrieval(client)

        reranker_id = resolve_model(pipeline_id, "default", "reranker", local=False)
        self.cohere_client = RerankRequestHandler(reranker_id)

        # The shared-embedding optimization only holds if every sub-pipeline
        # that receives the pre-embedded vectors uses the same embedding model.
        self._assert_shared_embedding_model()

    def _assert_shared_embedding_model(self) -> None:
        """Guard the shared-embedding optimization against misconfiguration.

        ``__call__`` embeds the search query once (with this orchestrator's
        embedding model) and reuses that vector across the
        segment, transcription, and page-chunk sub-pipelines. A hybrid search
        only returns meaningful results when the query vector comes from the
        same embedding model — hence the same vector space and dimension — the
        sub-pipeline would have used itself. These three pipelines are
        independent ``llm_configuration`` entries
        (``lecture_retrieval_pipeline``,
        ``lecture_unit_segment_retrieval_pipeline`` and
        ``lecture_transcriptions_retrieval_pipeline``), so a deployment could
        point them at different embedding models. Rather than silently searching
        with mismatched vectors (bad results, or a dimension error raised deep
        inside Weaviate), fail fast at construction with an actionable message.
        """
        shared_model_id = self.llm_embedding.model_id
        mismatches = {
            consumer: sub_pipeline.llm_embedding.model_id
            for consumer, sub_pipeline in (
                (
                    "segment retrieval (lecture_unit_segment_retrieval_pipeline)",
                    self.lecture_unit_segment_pipeline,
                ),
                (
                    "transcription retrieval (lecture_transcriptions_retrieval_pipeline)",
                    self.lecture_transcription_pipeline,
                ),
                (
                    "page-chunk retrieval (lecture_retrieval_pipeline)",
                    self.lecture_unit_page_chunk_pipeline,
                ),
            )
            if sub_pipeline.llm_embedding.model_id != shared_model_id
        }
        if mismatches:
            raise LlmConfigurationError(
                "Lecture retrieval reuses one set of query embeddings across the "
                "segment, transcription and page-chunk sub-pipelines, so they must "
                "all share the embedding model configured for "
                f"'lecture_retrieval_pipeline' ('{shared_model_id}'). Mismatched "
                f"embedding models: {mismatches}. Align the 'embedding' entries in "
                "llm_configuration for these pipelines."
            )

    @observe(name="Lecture Retrieval")
    def __call__(
        self,
        search_query: str,
        course_id: int,
        lecture_id: int = None,
        lecture_unit_id: int = None,
        base_url: str = None,
    ) -> LectureRetrievalDTO:
        """Retrieve the lecture content that matches a search query.

        The agent writes ``search_query`` itself: a self-contained query in the
        language of the course material. It is embedded once, searched in the
        slides, transcriptions and segment summaries, and the results are
        reranked against it.
        """
        with timed_span("LectureRetrieval", "get_lecture_unit"):
            with TracedThreadPoolExecutor(max_workers=2) as executor:
                lecture_unit_future = executor.submit(
                    self.get_lecture_unit,
                    course_id,
                    lecture_id,
                    lecture_unit_id,
                    base_url,
                )
                transcriptions_exist_future = executor.submit(
                    self.lecture_unit_has_transcriptions,
                    course_id,
                    lecture_id,
                    lecture_unit_id,
                    base_url,
                )
                lecture_unit = lecture_unit_future.result()
                transcriptions_exist = transcriptions_exist_future.result()
        if lecture_unit is None:
            return LectureRetrievalDTO(
                lecture_transcriptions=[],
                lecture_unit_page_chunks=[],
                lecture_unit_segments=[],
            )
        if not transcriptions_exist:
            logger.info(
                "Lecture retrieval: no transcriptions for unit — skipping transcription domain"
            )

        with timed_span("LectureRetrieval", "query_embeddings"):
            query_vector = self.llm_embedding.embed(search_query)

        with timed_span("LectureRetrieval", "search_pipelines"):
            (
                lecture_unit_segments,
                lecture_transcriptions,
                lecture_unit_page_chunks,
            ) = self.call_lecture_pipelines(
                lecture_unit, search_query, transcriptions_exist, query_vector
            )

        # Fetch the segments' surrounding transcriptions/page chunks
        # concurrently: these are independent Weaviate lookups (two per
        # segment) that used to run sequentially.
        if lecture_unit_segments:
            with timed_span("LectureRetrieval", "segment_content_fetch"):
                with TracedThreadPoolExecutor(max_workers=8) as executor:
                    transcription_futures = []
                    if transcriptions_exist:
                        transcription_futures = [
                            executor.submit(
                                self.get_lecture_transcription_of_lecture_unit,
                                segment,
                            )
                            for segment in lecture_unit_segments
                        ]
                    page_chunk_futures = [
                        executor.submit(
                            self.get_lecture_page_chunks_of_lecture_unit, segment
                        )
                        for segment in lecture_unit_segments
                    ]
                    for future in transcription_futures:
                        lecture_transcriptions += future.result()
                    for future in page_chunk_futures:
                        lecture_unit_page_chunks += future.result()

        # Remove duplicate lecture transcriptions
        unique_transcriptions = {}
        for transcription in lecture_transcriptions:
            unique_transcriptions[transcription.uuid] = transcription
        lecture_transcriptions = list(unique_transcriptions.values())

        # Remove duplicate lecture page chunks
        unique_page_chunks = {}
        for page_chunk in lecture_unit_page_chunks:
            unique_page_chunks[page_chunk.uuid] = page_chunk
        lecture_unit_page_chunks = list(unique_page_chunks.values())

        with timed_span("LectureRetrieval", "final_rerank"):
            with TracedThreadPoolExecutor(max_workers=2) as executor:
                transcriptions_future = executor.submit(
                    self.rerank_or_empty,
                    search_query,
                    lecture_transcriptions,
                    7,
                    "segment_text",
                )
                page_chunks_future = executor.submit(
                    self.rerank_or_empty,
                    search_query,
                    lecture_unit_page_chunks,
                    7,
                    "page_text_content",
                )
                lecture_transcriptions = transcriptions_future.result()
                lecture_unit_page_chunks = page_chunks_future.result()

        return LectureRetrievalDTO(
            lecture_unit_segments=lecture_unit_segments,
            lecture_transcriptions=lecture_transcriptions,
            lecture_unit_page_chunks=lecture_unit_page_chunks,
        )

    def course_material_language(
        self, course_id: int, base_url: Optional[str] = None
    ) -> Optional[str]:
        """The stored language of the course's lecture material, from one unit."""
        course_filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
            course_id
        )
        if base_url is not None:
            course_filter &= artemis_instance_filter(LectureUnitSchema, base_url)
        result = self.lecture_unit_collection.query.fetch_objects(
            filters=course_filter,
            limit=1,
            return_properties=[LectureUnitSchema.COURSE_LANGUAGE.value],
        )
        if not result.objects:
            return None
        return result.objects[0].properties.get(LectureUnitSchema.COURSE_LANGUAGE.value)

    def lecture_unit_has_transcriptions(
        self,
        course_id: int,
        lecture_id: int = None,
        lecture_unit_id: int = None,
        base_url: Optional[str] = None,
    ) -> bool:
        cache_key = (course_id, lecture_id, lecture_unit_id, base_url)
        if not hasattr(self, "_transcription_presence_cache"):
            self._transcription_presence_cache = {}
        if cache_key in self._transcription_presence_cache:
            return self._transcription_presence_cache[cache_key]

        transcription_filter = Filter.by_property(
            LectureTranscriptionSchema.COURSE_ID.value
        ).equal(course_id)
        if lecture_id is not None:
            transcription_filter &= Filter.by_property(
                LectureTranscriptionSchema.LECTURE_ID.value
            ).equal(lecture_id)
        if lecture_unit_id is not None:
            transcription_filter &= Filter.by_property(
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value
            ).equal(lecture_unit_id)
        # Another Artemis instance can use the same course id; only its own
        # transcriptions may decide whether the transcription search runs.
        if base_url:
            transcription_filter &= Filter.by_property(
                LectureTranscriptionSchema.BASE_URL.value
            ).equal(base_url)

        transcriptions = self.lecture_transcription_collection.query.fetch_objects(
            filters=transcription_filter,
            limit=1,
        ).objects
        transcriptions_exist = len(transcriptions) > 0
        self._transcription_presence_cache[cache_key] = transcriptions_exist
        return transcriptions_exist

    def rerank_or_empty(
        self,
        query: str,
        documents: List[Any],
        top_n: int,
        content_field_name: str,
    ) -> List[Any]:
        if not documents:
            return []

        return self.cohere_client.rerank(
            query,
            documents,
            top_n=top_n,
            content_field_name=content_field_name,
        )

    def fetch_context_content(
        self,
        course_id: int,
        base_url: Optional[str],
        context_pages: Optional[List[Dict[str, Any]]] = None,
        context_timestamps: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[
        List[LectureUnitPageChunkRetrievalDTO],
        List[LectureTranscriptionRetrievalDTO],
    ]:
        """Fetch the exact lecture content the student is currently viewing.

        This is independent of the RAG lecture retrieval tool. It directly looks
        up the slide page chunks and transcription segments referenced by the
        student's current position (the slides/video contexts) so the content can
        be pasted straight into the prompt, without the agent needing to call any
        tool.

        Args:
            course_id: The course the student is currently in.
            base_url: Artemis base URL used to scope the lookup.
            context_pages: List of ``{"lecture_unit_id", "page"}`` entries.
            context_timestamps: List of ``{"lecture_unit_id", "timestamp"}`` entries.

        Returns:
            A tuple of (page chunks, transcription segments) for the current
            position.
        """
        page_chunks: List[LectureUnitPageChunkRetrievalDTO] = []
        transcriptions: List[LectureTranscriptionRetrievalDTO] = []

        for context_page in context_pages or []:
            lecture_unit_id = context_page.get("lecture_unit_id")
            page = context_page.get("page")
            if lecture_unit_id is None or page is None:
                continue
            if not self._is_lecture_unit_released(course_id, lecture_unit_id, base_url):
                continue
            page_chunks.extend(
                self._fetch_page_chunks_by_page(
                    course_id, lecture_unit_id, page, base_url
                )
            )

        for context_timestamp in context_timestamps or []:
            lecture_unit_id = context_timestamp.get("lecture_unit_id")
            timestamp = context_timestamp.get("timestamp")
            if lecture_unit_id is None or timestamp is None:
                continue
            if not self._is_lecture_unit_released(course_id, lecture_unit_id, base_url):
                continue
            transcriptions.extend(
                self._fetch_transcriptions_by_timestamp(
                    course_id, lecture_unit_id, timestamp, base_url
                )
            )

        return page_chunks, transcriptions

    def _is_lecture_unit_released(
        self, course_id: int, lecture_unit_id: int, base_url: Optional[str]
    ) -> bool:
        cache_key = (course_id, lecture_unit_id, base_url)
        if not hasattr(self, "_release_cache"):
            self._release_cache = {}
        if cache_key in self._release_cache:
            return self._release_cache[cache_key]
        unit_filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
            course_id
        )
        unit_filter &= Filter.by_property(
            LectureUnitSchema.LECTURE_UNIT_ID.value
        ).equal(lecture_unit_id)
        if base_url is not None:
            unit_filter &= artemis_instance_filter(LectureUnitSchema, base_url)
        units = self.lecture_unit_collection.query.fetch_objects(
            filters=unit_filter, limit=1
        ).objects
        released = bool(units) and is_unit_released(units[0].properties)
        self._release_cache[cache_key] = released
        return released

    def _fetch_page_chunks_by_page(
        self,
        course_id: int,
        lecture_unit_id: int,
        page_number: int,
        base_url: Optional[str],
    ) -> List[LectureUnitPageChunkRetrievalDTO]:
        page_chunk_filter = Filter.by_property(
            LectureUnitPageChunkSchema.COURSE_ID.value
        ).equal(course_id)
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
        ).equal(lecture_unit_id)
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.PAGE_NUMBER.value
        ).equal(page_number)
        if base_url is not None:
            page_chunk_filter &= artemis_instance_filter(
                LectureUnitPageChunkSchema, base_url
            )

        # High limit so all chunks of one page are fetched, not just Weaviate's
        # default first batch.
        lecture_page_chunks = (
            self.lecture_unit_page_chunk_collection.query.fetch_objects(
                filters=page_chunk_filter,
                limit=10_000,
            ).objects
        )

        return [
            dto
            for chunk in lecture_page_chunks
            if (
                dto := self.lecture_unit_page_chunk_pipeline.generate_retrieval_dtos(
                    chunk.properties, str(chunk.uuid)
                )
            )
        ]

    def _fetch_transcriptions_by_timestamp(
        self,
        course_id: int,
        lecture_unit_id: int,
        timestamp: float,
        base_url: Optional[str],
    ) -> List[LectureTranscriptionRetrievalDTO]:
        transcription_filter = Filter.by_property(
            LectureTranscriptionSchema.COURSE_ID.value
        ).equal(course_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.LECTURE_UNIT_ID.value
        ).equal(lecture_unit_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.SEGMENT_START_TIME.value
        ).less_or_equal(timestamp)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.SEGMENT_END_TIME.value
        ).greater_than(timestamp)
        if base_url is not None:
            transcription_filter &= artemis_instance_filter(
                LectureTranscriptionSchema, base_url
            )

        lecture_transcriptions = (
            self.lecture_transcription_collection.query.fetch_objects(
                filters=transcription_filter
            ).objects
        )

        return [
            dto
            for transcription in lecture_transcriptions
            if (
                dto := self.lecture_transcription_pipeline.generate_retrieval_dtos(
                    transcription.properties, str(transcription.uuid)
                )
            )
        ]

    def _fetch_first_released_unit(self, lecture_filter):
        offset = 0
        page_size = 100
        candidate_ceiling = 10_000
        while offset < candidate_ceiling:
            page_limit = min(page_size, candidate_ceiling - offset)
            lecture_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_filter,
                limit=page_limit,
                offset=offset,
            ).objects
            released_unit = next(
                (unit for unit in lecture_units if is_unit_released(unit.properties)),
                None,
            )
            if released_unit is not None:
                return released_unit
            if len(lecture_units) < page_limit:
                return None
            offset += len(lecture_units)
        return None

    def get_lecture_unit(
        self,
        course_id: int,
        lecture_id: int = None,
        lecture_unit_id: int = None,
        base_url: str = None,
    ):
        lecture_filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
            course_id
        )

        if base_url is not None:
            lecture_filter &= artemis_instance_filter(LectureUnitSchema, base_url)

        if lecture_id is not None and lecture_unit_id is not None:
            lecture_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_ID.value
            ).equal(lecture_id)
            lecture_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ).equal(lecture_unit_id)

            released_unit = self._fetch_first_released_unit(lecture_filter)
            if released_unit is None:
                return None

            lecture_unit = released_unit.properties
            lecture_unit_uuid = str(released_unit.uuid)

            return LectureUnitRetrievalDTO(
                uuid=lecture_unit_uuid,
                course_id=lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name=lecture_unit[LectureUnitSchema.COURSE_NAME.value],
                course_description=lecture_unit[
                    LectureUnitSchema.COURSE_DESCRIPTION.value
                ],
                course_language=lecture_unit[LectureUnitSchema.COURSE_LANGUAGE.value],
                lecture_id=lecture_unit[LectureUnitSchema.LECTURE_ID.value],
                lecture_name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
                lecture_unit_id=lecture_unit[LectureUnitSchema.LECTURE_UNIT_ID.value],
                lecture_unit_name=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_NAME.value
                ],
                lecture_unit_link=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_LINK.value
                ],
                video_link=lecture_unit[LectureUnitSchema.VIDEO_LINK.value],
                base_url=base_url,
                lecture_unit_summary=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_SUMMARY.value
                ],
            )

        elif lecture_id is not None:
            lecture_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_ID.value
            ).equal(lecture_id)
            released_unit = self._fetch_first_released_unit(lecture_filter)
            if released_unit is None:
                return None
            lecture_unit = released_unit.properties
            lecture_unit_uuid = str(released_unit.uuid)

            return LectureUnitRetrievalDTO(
                uuid=lecture_unit_uuid,
                course_id=lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name=lecture_unit[LectureUnitSchema.COURSE_NAME.value],
                course_description=lecture_unit[
                    LectureUnitSchema.COURSE_DESCRIPTION.value
                ],
                course_language=lecture_unit[LectureUnitSchema.COURSE_LANGUAGE.value],
                lecture_id=lecture_unit[LectureUnitSchema.LECTURE_ID.value],
                lecture_name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
                lecture_unit_id=None,
                lecture_unit_name=None,
                lecture_unit_link=None,
                video_link=None,
                base_url=base_url,
                lecture_unit_summary=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_SUMMARY.value
                ],
            )

        else:
            released_unit = self._fetch_first_released_unit(lecture_filter)
            if released_unit is None:
                return None
            lecture_unit = released_unit.properties
            lecture_unit_uuid = str(released_unit.uuid)

            return LectureUnitRetrievalDTO(
                uuid=lecture_unit_uuid,
                course_id=lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name=lecture_unit[LectureUnitSchema.COURSE_NAME.value],
                course_description=lecture_unit[
                    LectureUnitSchema.COURSE_DESCRIPTION.value
                ],
                course_language=lecture_unit[LectureUnitSchema.COURSE_LANGUAGE.value],
                lecture_id=None,
                lecture_name=None,
                lecture_unit_id=None,
                lecture_unit_name=None,
                lecture_unit_link=None,
                video_link=None,
                base_url=base_url,
                lecture_unit_summary=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_SUMMARY.value
                ],
            )

    def call_lecture_pipelines(
        self,
        lecture_unit: LectureUnitRetrievalDTO,
        search_query: str,
        transcriptions_exist: bool,
        query_vector: List[float],
    ):
        """
        Search segments, transcriptions and slide chunks for the query in parallel.
        """
        worker_count = 3 if transcriptions_exist else 2
        with TracedThreadPoolExecutor(max_workers=worker_count) as executor:
            lecture_unit_segments_future = executor.submit(
                self.lecture_unit_segment_pipeline,
                search_query,
                lecture_unit,
                query_vector=query_vector,
            )
            lecture_transcriptions_future = None
            if transcriptions_exist:
                lecture_transcriptions_future = executor.submit(
                    self.lecture_transcription_pipeline,
                    search_query,
                    lecture_unit,
                    query_vector=query_vector,
                )
            lecture_unit_page_chunks_future = executor.submit(
                self.lecture_unit_page_chunk_pipeline,
                search_query,
                lecture_unit,
                query_vector=query_vector,
            )

            lecture_unit_segments: List[LectureUnitSegmentRetrievalDTO] = (
                lecture_unit_segments_future.result()
            )
            lecture_transcriptions: List[LectureTranscriptionRetrievalDTO] = []
            if lecture_transcriptions_future is not None:
                lecture_transcriptions = lecture_transcriptions_future.result()
            lecture_unit_page_chunks: List[LectureUnitPageChunkRetrievalDTO] = (
                lecture_unit_page_chunks_future.result()
            )

        return (
            lecture_unit_segments,
            lecture_transcriptions,
            lecture_unit_page_chunks,
        )

    def get_lecture_transcription_of_lecture_unit(
        self, lecture_unit_segment: LectureUnitSegmentRetrievalDTO
    ):
        target_page_number = lecture_unit_segment.display_page_number

        # Slides with unknown display page (-1) do not match any transcription
        if target_page_number == -1 and lecture_unit_segment.page_number != -1:
            return []

        # A None in any filter value crashes the Weaviate gRPC query ("unknown
        # value type <nil>"); such segments cannot match a transcription anyway.
        filter_values = (
            lecture_unit_segment.course_id,
            lecture_unit_segment.lecture_id,
            lecture_unit_segment.lecture_unit_id,
            target_page_number,
            lecture_unit_segment.base_url,
        )
        if any(value is None for value in filter_values):
            logger.debug(
                "Skipping transcription lookup for segment %s: missing filter values",
                lecture_unit_segment.uuid,
            )
            return []

        transcription_filter = Filter.by_property(
            LectureTranscriptionSchema.COURSE_ID.value
        ).equal(lecture_unit_segment.course_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.LECTURE_ID.value
        ).equal(lecture_unit_segment.lecture_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.LECTURE_UNIT_ID.value
        ).equal(lecture_unit_segment.lecture_unit_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.PAGE_NUMBER.value
        ).equal(target_page_number)
        transcription_filter &= artemis_instance_filter(
            LectureTranscriptionSchema, lecture_unit_segment.base_url
        )

        lecture_transcriptions = (
            self.lecture_transcription_collection.query.fetch_objects(
                filters=transcription_filter
            ).objects
        )

        return [
            dto
            for transcription in lecture_transcriptions
            if (
                dto := self.lecture_transcription_pipeline.generate_retrieval_dtos(
                    transcription.properties, str(transcription.uuid)
                )
            )
            is not None
        ]

    def get_lecture_page_chunks_of_lecture_unit(
        self, lecture_unit_segment: LectureUnitSegmentRetrievalDTO
    ):
        filter_values = (
            lecture_unit_segment.course_id,
            lecture_unit_segment.lecture_id,
            lecture_unit_segment.lecture_unit_id,
            lecture_unit_segment.page_number,
            lecture_unit_segment.base_url,
        )
        if any(value is None for value in filter_values):
            logger.debug(
                "Skipping page-chunk lookup for segment %s: missing filter values",
                lecture_unit_segment.uuid,
            )
            return []

        page_chunk_filter = Filter.by_property(
            LectureUnitPageChunkSchema.COURSE_ID.value
        ).equal(lecture_unit_segment.course_id)
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_ID.value
        ).equal(lecture_unit_segment.lecture_id)
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
        ).equal(lecture_unit_segment.lecture_unit_id)
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.PAGE_NUMBER.value
        ).equal(lecture_unit_segment.page_number)
        page_chunk_filter &= artemis_instance_filter(
            LectureUnitPageChunkSchema, lecture_unit_segment.base_url
        )

        lecture_page_chunks = (
            self.lecture_unit_page_chunk_collection.query.fetch_objects(
                filters=page_chunk_filter
            ).objects
        )

        return [
            LectureUnitPageChunkRetrievalDTO(
                str(chunk.uuid),
                lecture_unit_segment.course_id,
                lecture_unit_segment.course_name,
                lecture_unit_segment.course_description,
                lecture_unit_segment.lecture_id,
                lecture_unit_segment.lecture_name,
                lecture_unit_segment.lecture_unit_id,
                lecture_unit_segment.lecture_unit_name,
                lecture_unit_segment.lecture_unit_link,
                chunk.properties[LectureUnitPageChunkSchema.COURSE_LANGUAGE.value],
                chunk.properties[LectureUnitPageChunkSchema.PAGE_NUMBER.value],
                chunk.properties.get(
                    LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
                    chunk.properties[LectureUnitPageChunkSchema.PAGE_NUMBER.value],
                ),
                chunk.properties[LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value],
                lecture_unit_segment.base_url,
            )
            for chunk in lecture_page_chunks
            if is_slide_visible(chunk.properties)
        ]
