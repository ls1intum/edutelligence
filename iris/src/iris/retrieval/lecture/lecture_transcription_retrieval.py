from asyncio.log import logger

from app import (
    LectureTranscriptionRetrievalDTO,
    LectureUnitRetrievalDTO,
)
from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from src.iris.llm import (
    BasicRequestHandler,
    CapabilityRequestHandler,
    CompletionArguments,
    RequirementList,
)
from src.iris.llm.langchain import IrisLangchainChatModel
from src.iris.llm.request_handler.rerank_request_handler import RerankRequestHandler
from src.iris.pipeline import Pipeline
from src.iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from src.iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)


class LectureTranscriptionRetrieval(Pipeline):
    def __init__(self, client: WeaviateClient):
        super().__init__(implementation_id="lecture_transcriptions_retrieval_pipeline")
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.25,
                context_length=16385,
                privacy_compliance=True,
            )
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.llm_embedding = BasicRequestHandler("embedding-small")
        self.pipeline = self.llm | StrOutputParser()
        self.collection = init_lecture_transcription_schema(client)
        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.cohere_client = RerankRequestHandler("cohere")
        self.tokens = []

    def __call__(
        self,
        student_query: str,
        rewritten_query: str,
        hypothetical_answer: str,
        lecture_unit_dto: LectureUnitRetrievalDTO,
        result_limit: int = 10,
        hybrid_factor: float = 0.9,
        top_n_reranked_results: int = 7,
    ):
        results_rewritten_query = self.search_in_db(
            lecture_unit_dto, rewritten_query, hybrid_factor, result_limit
        )
        results_hypothetical_answer = self.search_in_db(
            lecture_unit_dto, hypothetical_answer, hybrid_factor, result_limit
        )

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

    def search_in_db(
        self,
        lecture_unit_dto: LectureUnitRetrievalDTO,
        query: str,
        hybrid_factor: float,
        result_limit: int,
    ):
        """
        Search the database for the given query.
        """
        logger.info(f"Searching in the database for query: {query}")
        # Initialize filter to None by default
        filter_weaviate = None

        # Check if course_id is provided
        if lecture_unit_dto.course_id is not None:
            # Create a filter for course_id
            filter_weaviate = Filter.by_property(
                LectureTranscriptionSchema.COURSE_ID.value
            ).equal(lecture_unit_dto.course_id)
        if lecture_unit_dto.lecture_id is not None:
            filter_weaviate = Filter.by_property(
                LectureTranscriptionSchema.LECTURE_ID.value
            ).equal(lecture_unit_dto.lecture_id)
        if lecture_unit_dto.base_url is not None:
            filter_weaviate = Filter.by_property(
                LectureTranscriptionSchema.BASE_URL.value
            ).equal(lecture_unit_dto.base_url)

        vec = self.llm_embedding.embed(query)
        return_value = self.collection.query.hybrid(
            query=query,
            alpha=hybrid_factor,
            vector=vec,
            limit=result_limit,
            filters=filter_weaviate,
        )
        return return_value.objects

    def generate_retrieval_dtos(self, lecture_transcription_segment, uuid):
        lecture_unit_filter = Filter.by_property(
            LectureUnitSchema.COURSE_ID.value
        ).equal(
            lecture_transcription_segment[LectureTranscriptionSchema.COURSE_ID.value]
        )
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.LECTURE_ID.value
        ).equal(
            lecture_transcription_segment[LectureTranscriptionSchema.LECTURE_ID.value]
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
        if len(lecture_units) == 0:
            return None
        else:
            lecture_unit = lecture_units[0].properties
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
                lecture_unit_link=lecture_unit[
                    LectureUnitSchema.LECTURE_UNIT_LINK.value
                ],
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
