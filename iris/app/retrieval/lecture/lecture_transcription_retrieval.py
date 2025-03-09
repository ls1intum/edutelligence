from typing import List

from langchain_core.output_parsers import StrOutputParser

from app.common.pyris_message import PyrisMessage
from app.domain.retrieval.lecture.lecture_retrieval_dto import LectureUnitRetrievalDTO, LectureTranscriptionRetrievalDTO
from app.llm import (
    CapabilityRequestHandler,
    RequirementList,
    CompletionArguments,
    BasicRequestHandler,
)
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline
from weaviate import WeaviateClient

from app.pipeline.shared.cohere_reranker_pipeline import CohereRerankerPipeline
from app.pipeline.shared.reranker_pipeline import RerankerPipeline
from app.vector_database.lecture_transcription_schema import (
    init_lecture_transcription_schema, LectureTranscriptionSchema,
)
from asyncio.log import logger
from weaviate.classes.query import Filter
from app.retrieval.lecture.lecture_retrieval_utils import merge_retrieved_chunks
from app.vector_database.lecture_unit_schema import LectureUnitSchema, init_lecture_unit_schema


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
        self.reranker_pipeline = CohereRerankerPipeline()
        self.tokens = []

    def __call__(
        self,
        rewritten_query: str,
        hypothetical_answer: str,
        lecture_unit_dto: LectureUnitRetrievalDTO,
        student_query: str,
        result_limit: int,
        hybrid_factor: float,
        chat_history: list[PyrisMessage],
    ):
        """
        # 1. Anfrage mit Queries an Weaviate
        # 2. Merge results in eine Liste
        # 3. Reranken
        # 4. DTOs zurückgeben
        """
        print("LectureTranscriptionRetrieval is running")

        results_rewritten_query = self.search_in_db(lecture_unit_dto, rewritten_query, hybrid_factor, result_limit)
        results_hypothetical_answer = self.search_in_db(lecture_unit_dto, hypothetical_answer, hybrid_factor, result_limit)
        merged_answers = merge_retrieved_chunks(results_rewritten_query, results_hypothetical_answer)
        reranked_answers = self.reranker_pipeline(query=student_query, documents=merged_answers, top_n=7, content_field_name=LectureTranscriptionSchema.SEGMENT_TEXT.value)

        lecture_transcription_retrieval_dtos = []
        for lecture_transcription_segment in reranked_answers:
            lecture_transcription_retrieval_dto = self.generate_retrieval_dtos(lecture_transcription_segment)
            lecture_transcription_retrieval_dtos.append(lecture_transcription_retrieval_dto)
        return lecture_transcription_retrieval_dtos

    def search_in_db(self, lecture_unit_dto: LectureUnitRetrievalDTO, query: str, hybrid_factor: float,
        result_limit: int):
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
            return_properties=[
                LectureTranscriptionSchema.COURSE_ID.value,
                LectureTranscriptionSchema.LECTURE_ID.value,
                LectureTranscriptionSchema.PAGE_NUMBER.value,
                LectureTranscriptionSchema.BASE_URL.value,
                LectureTranscriptionSchema.SEGMENT_START_TIME.value,
                LectureTranscriptionSchema.SEGMENT_END_TIME.value,
                LectureTranscriptionSchema.SEGMENT_TEXT.value,
                LectureTranscriptionSchema.SEGMENT_SUMMARY.value,
            ],
            limit=result_limit,
            filters=filter_weaviate,
        )
        return return_value

    def generate_retrieval_dtos(self, lecture_transcription_segment):
        lecture_unit_filter = Filter.by_property(
            LectureUnitSchema.COURSE_ID.value
        ).equal(lecture_transcription_segment[LectureTranscriptionSchema.COURSE_ID.value])
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.LECTURE_ID.value
        ).equal(lecture_transcription_segment[LectureTranscriptionSchema.LECTURE_ID.value])
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.LECTURE_UNIT_ID.value
        ).equal(lecture_transcription_segment[LectureTranscriptionSchema.LECTURE_UNIT_ID.value])
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.BASE_URL.value
        ).equal(lecture_transcription_segment[LectureTranscriptionSchema.BASE_URL.value])

        lecture_units = self.lecture_unit_collection.query.fetch_objects(filters=lecture_unit_filter).objects
        if len(lecture_units) == 0:
            return None
        else:
            lecture_unit = lecture_units[0]
            lecture_transcription_dto = LectureTranscriptionRetrievalDTO(
                course_id = lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name = lecture_unit[LectureUnitSchema.COURSE_NAME.value],
                course_description = lecture_unit[LectureUnitSchema.COURSE_DESCRIPTION.value],
                lecture_id = lecture_unit[LectureUnitSchema.LECTURE_ID.value],
                lecture_name = lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
                lecture_unit_id = lecture_unit[LectureUnitSchema.LECTURE_UNIT_ID.value],
                lecture_unit_name = lecture_unit[LectureUnitSchema.LECTURE_UNIT_NAME.value],
                lecture_unit_link = lecture_unit[LectureUnitSchema.LECTURE_UNIT_LINK.value],
                language = lecture_transcription_segment[LectureTranscriptionSchema.LANGUAGE.value],
                segment_start_time = lecture_transcription_segment[LectureTranscriptionSchema.SEGMENT_START_TIME.value],
                segment_end_time = lecture_transcription_segment[LectureTranscriptionSchema.SEGMENT_END_TIME.value],
                page_number = lecture_transcription_segment[LectureTranscriptionSchema.PAGE_NUMBER.value],
                segment_summary = lecture_transcription_segment[LectureTranscriptionSchema.SEGMENT_SUMMARY.value],
                segment_text = lecture_transcription_segment[LectureTranscriptionSchema.SEGMENT_TEXT.value],
                base_url=lecture_unit[LectureUnitSchema.BASE_URL.value],
            )
            return lecture_transcription_dto
