from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureTranscriptionRetrievalDTO,
    LectureUnitRetrievalDTO,
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
from iris.retrieval.lecture.lecture_visibility import is_transcription_visible
from iris.tracing import TracedThreadPoolExecutor, observe
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


class LectureTranscriptionRetrieval(SubPipeline):
    """LectureTranscriptionRetrieval retrieves lecture transcription data from the database by applying search filters
    and processing the transcription segments."""

    def __init__(self, client: WeaviateClient, local: bool = False):
        super().__init__(implementation_id="lecture_transcriptions_retrieval_pipeline")
        pipeline_id = "lecture_transcriptions_retrieval_pipeline"
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
        self.collection = init_lecture_transcription_schema(client)
        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.lecture_unit_page_chunk_collection = init_lecture_unit_page_chunk_schema(
            client
        )
        reranker_id = resolve_model(pipeline_id, "default", "reranker", local=False)
        self.cohere_client = RerankRequestHandler(reranker_id)
        self.tokens = []
        # Per-request cache of lecture unit metadata, keyed by
        # (course_id, lecture_id, lecture_unit_id, base_url). Hits from the
        # same unit would otherwise trigger one identical Weaviate lookup each.
        self._lecture_unit_cache: dict = {}
        self._slide_visibility_cache: dict = {}

    @observe(name="Lecture Transcription Retrieval")
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
        lecture_transcription_retrieval_dtos = []
        for lecture_transcription_segment in results:
            lecture_transcription_retrieval_dto = self.generate_retrieval_dtos(
                lecture_transcription_segment.properties,
                str(lecture_transcription_segment.uuid),
            )
            if lecture_transcription_retrieval_dto is not None:
                lecture_transcription_retrieval_dtos.append(
                    lecture_transcription_retrieval_dto
                )

        reranked_answers = self.cohere_client.rerank(
            query=student_query,
            documents=lecture_transcription_retrieval_dtos,
            top_n=top_n_reranked_results,
            content_field_name="segment_text",
        )

        return reranked_answers

    @observe(name="Lecture Transcription: Search in DB")
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
            "[LECTURE_TRANSCRIPTION_RETRIEVAL] Searching in the database for query: %s",
            query,
        )
        # Initialize filter to None by default
        filter_weaviate = None

        # Check if course_id is provided
        if lecture_unit_dto.course_id is not None:
            # Create a filter for course_id
            filter_weaviate = Filter.by_property(
                LectureTranscriptionSchema.COURSE_ID.value
            ).equal(lecture_unit_dto.course_id)
        if lecture_unit_dto.lecture_id is not None:
            lecture_filter = Filter.by_property(
                LectureTranscriptionSchema.LECTURE_ID.value
            ).equal(lecture_unit_dto.lecture_id)
            filter_weaviate = (
                lecture_filter
                if filter_weaviate is None
                else filter_weaviate & lecture_filter
            )
        if lecture_unit_dto.base_url is not None:
            base_url_filter = Filter.by_property(
                LectureTranscriptionSchema.BASE_URL.value
            ).equal(lecture_unit_dto.base_url)
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

    def generate_retrieval_dtos(self, lecture_transcription_segment, uuid):
        cache_key = (
            lecture_transcription_segment[LectureTranscriptionSchema.COURSE_ID.value],
            lecture_transcription_segment[LectureTranscriptionSchema.LECTURE_ID.value],
            lecture_transcription_segment[
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value
            ],
            lecture_transcription_segment[LectureTranscriptionSchema.BASE_URL.value],
        )
        if cache_key in self._lecture_unit_cache:
            lecture_unit = self._lecture_unit_cache[cache_key]
        else:
            lecture_unit_filter = Filter.by_property(
                LectureUnitSchema.COURSE_ID.value
            ).equal(
                lecture_transcription_segment[
                    LectureTranscriptionSchema.COURSE_ID.value
                ]
            )
            lecture_unit_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_ID.value
            ).equal(
                lecture_transcription_segment[
                    LectureTranscriptionSchema.LECTURE_ID.value
                ]
            )
            lecture_unit_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ).equal(
                lecture_transcription_segment[
                    LectureTranscriptionSchema.LECTURE_UNIT_ID.value
                ]
            )
            lecture_unit_filter &= Filter.by_property(
                LectureUnitSchema.BASE_URL.value
            ).equal(
                lecture_transcription_segment[LectureTranscriptionSchema.BASE_URL.value]
            )

            lecture_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_unit_filter
            ).objects
            lecture_unit = (
                lecture_units[0].properties if len(lecture_units) > 0 else None
            )
            self._lecture_unit_cache[cache_key] = lecture_unit

        if lecture_unit is None:
            return None
        associated_slide = self._get_associated_slide(
            cache_key, lecture_transcription_segment
        )
        if not is_transcription_visible(
            lecture_transcription_segment, lecture_unit, associated_slide
        ):
            return None
        else:
            lecture_transcription_dto = LectureTranscriptionRetrievalDTO(
                uuid=uuid,
                course_id=lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name=lecture_unit[LectureUnitSchema.COURSE_NAME.value],
                course_description=lecture_unit[
                    LectureUnitSchema.COURSE_DESCRIPTION.value
                ],
                lecture_id=lecture_unit[LectureUnitSchema.LECTURE_ID.value],
                lecture_name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
                lecture_unit_id=lecture_unit[LectureUnitSchema.LECTURE_UNIT_ID.value],
                lecture_unit_name=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_NAME.value
                ],
                video_link=lecture_unit[LectureUnitSchema.VIDEO_LINK.value],
                language=lecture_transcription_segment[
                    LectureTranscriptionSchema.LANGUAGE.value
                ],
                segment_start_time=lecture_transcription_segment[
                    LectureTranscriptionSchema.SEGMENT_START_TIME.value
                ],
                segment_end_time=lecture_transcription_segment[
                    LectureTranscriptionSchema.SEGMENT_END_TIME.value
                ],
                page_number=lecture_transcription_segment[
                    LectureTranscriptionSchema.PAGE_NUMBER.value
                ],
                segment_summary=lecture_transcription_segment[
                    LectureTranscriptionSchema.SEGMENT_SUMMARY.value
                ],
                segment_text=lecture_transcription_segment[
                    LectureTranscriptionSchema.SEGMENT_TEXT.value
                ],
                base_url=lecture_unit[LectureUnitSchema.BASE_URL.value],
            )
            return lecture_transcription_dto

    def _get_associated_slide(self, cache_key, transcription_properties):
        if cache_key not in self._slide_visibility_cache:
            slide_filter = Filter.all_of(
                [
                    Filter.by_property(
                        LectureUnitPageChunkSchema.COURSE_ID.value
                    ).equal(cache_key[0]),
                    Filter.by_property(
                        LectureUnitPageChunkSchema.LECTURE_ID.value
                    ).equal(cache_key[1]),
                    Filter.by_property(
                        LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
                    ).equal(cache_key[2]),
                    Filter.by_property(LectureUnitPageChunkSchema.BASE_URL.value).equal(
                        cache_key[3]
                    ),
                ]
            )
            chunks = self.lecture_unit_page_chunk_collection.query.fetch_objects(
                filters=slide_filter,
                limit=10_000,
                return_properties=[
                    LectureUnitPageChunkSchema.BASE_URL.value,
                    LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                    LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
                    LectureUnitPageChunkSchema.HIDDEN_UNTIL.value,
                ],
            ).objects
            slides_by_display_page: dict[int, dict[int, dict]] = {}
            for chunk in chunks:
                display_page = chunk.properties.get(
                    LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
                    chunk.properties.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value),
                )
                physical_page = chunk.properties.get(
                    LectureUnitPageChunkSchema.PAGE_NUMBER.value
                )
                if display_page is None or physical_page is None:
                    continue
                slides_by_display_page.setdefault(int(display_page), {})[
                    int(physical_page)
                ] = chunk.properties
            self._slide_visibility_cache[cache_key] = {
                display_page: list(slides_by_physical_page.values())
                for display_page, slides_by_physical_page in slides_by_display_page.items()
            }

        page_number = transcription_properties.get(
            LectureTranscriptionSchema.PAGE_NUMBER.value
        )
        try:
            return self._slide_visibility_cache[cache_key].get(int(page_number))
        except (TypeError, ValueError):
            return None
