from asyncio.log import logger
from typing import List

from langsmith import traceable
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from app.common.token_usage_dto import TokenUsageDTO
from app.common.message_converters import convert_iris_message_to_langchain_message
from app.common.pyris_message import PyrisMessage
from app.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureUnitRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from app.llm.langchain import IrisLangchainChatModel
from app.llm.request_handler.rerank_request_handler import RerankRequestHandler
from app.pipeline import Pipeline

from app.llm import (
    BasicRequestHandler,
    CompletionArguments,
    CapabilityRequestHandler,
    RequirementList,
)
from app.pipeline.shared.reranker_pipeline import RerankerPipeline
from app.vector_database.lecture_unit_page_chunk_schema import (
    init_lecture_unit_page_chunk_schema,
    LectureUnitPageChunkSchema,
)
from langchain_core.output_parsers import StrOutputParser
from app.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)


def _add_last_four_messages_to_prompt(
    prompt,
    chat_history: List[PyrisMessage],
):
    """
    Adds the chat history and user question to the prompt
        :param chat_history: The chat history
        :param user_question: The user question
        :return: The prompt with the chat history
    """
    if chat_history is not None and len(chat_history) > 0:
        num_messages_to_take = min(len(chat_history), 4)
        last_messages = chat_history[-num_messages_to_take:]
        chat_history_messages = [
            convert_iris_message_to_langchain_message(message)
            for message in last_messages
        ]
        prompt += chat_history_messages
    return prompt


class LecturePageChunkRetrieval(Pipeline):
    """
    Class for retrieving lecture data from the database.
    """

    tokens: List[TokenUsageDTO]

    def __init__(self, client: WeaviateClient, **kwargs):
        super().__init__(implementation_id="lecture_retrieval_pipeline")
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
        self.cohere_client = RerankRequestHandler("cohere")

        self.pipeline = self.llm | StrOutputParser()
        self.lecture_unit_page_chunk_collection = init_lecture_unit_page_chunk_schema(
            client
        )
        self.lecture_unit_collection = init_lecture_unit_schema(client)

        self.reranker_pipeline = RerankerPipeline()
        self.tokens = []

    @traceable(name="Full Lecture Retrieval")
    def __call__(
        self,
        student_query: str,
        rewritten_student_query: str,
        hypothetical_answer: str,
        lecture_unit: LectureUnitRetrievalDTO,
        result_limit: int = 10,
        hybrid_factor: float = 0.9,
        top_n_reranked_results: int = 7,
    ) -> list[LectureUnitPageChunkRetrievalDTO]:
        """
        Retrieve lecture data from the database.
        """

        basic_lecture_chunks = self.search_in_db(
            query=rewritten_student_query,
            hybrid_factor=0.9,
            result_limit=result_limit,
            lecture_unit_dto=lecture_unit,
        )

        hyde_lecture_chunks = self.search_in_db(
            query=hypothetical_answer,
            hybrid_factor=0.9,
            result_limit=result_limit,
            lecture_unit_dto=lecture_unit,
        )

        unique = {}
        for segment in basic_lecture_chunks + hyde_lecture_chunks:
            unique[segment.uuid] = segment
        results = list(unique.values())

        page_chunks = [
            dto
            for chunk in results
            if (dto := self.generate_retrieval_dtos(chunk.properties, str(chunk.uuid)))
            is not None
        ]

        reranked_page_chunks = self.cohere_client.rerank(
            student_query, page_chunks, top_n_reranked_results, "page_text_content"
        )
        return reranked_page_chunks

    @traceable(name="Retrieval: Search in DB")
    def search_in_db(
        self,
        query: str,
        hybrid_factor: float,
        result_limit: int,
        lecture_unit_dto: LectureUnitRetrievalDTO,
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
                LectureUnitPageChunkSchema.COURSE_ID.value
            ).equal(lecture_unit_dto.course_id)
        if lecture_unit_dto.lecture_id is not None:
            filter_weaviate = Filter.by_property(
                LectureUnitPageChunkSchema.LECTURE_ID.value
            ).equal(lecture_unit_dto.lecture_id)
        if lecture_unit_dto.base_url is not None:
            filter_weaviate = Filter.by_property(
                LectureUnitPageChunkSchema.BASE_URL.value
            ).equal(lecture_unit_dto.base_url)

        vec = self.llm_embedding.embed(query)
        return_value = self.lecture_unit_page_chunk_collection.query.hybrid(
            query=query,
            alpha=hybrid_factor,
            vector=vec,
            limit=result_limit,
            filters=filter_weaviate,
        )
        return return_value.objects

    def generate_retrieval_dtos(self, lecture_page_chunk, uuid):
        lecture_unit_filter = Filter.by_property(
            LectureUnitSchema.COURSE_ID.value
        ).equal(lecture_page_chunk[LectureUnitPageChunkSchema.COURSE_ID.value])
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.LECTURE_ID.value
        ).equal(lecture_page_chunk[LectureUnitPageChunkSchema.LECTURE_ID.value])
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.LECTURE_UNIT_ID.value
        ).equal(lecture_page_chunk[LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value])
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.BASE_URL.value
        ).equal(lecture_page_chunk[LectureUnitPageChunkSchema.BASE_URL.value])

        lecture_units = self.lecture_unit_collection.query.fetch_objects(
            filters=lecture_unit_filter
        ).objects
        if len(lecture_units) == 0:
            return None
        else:
            lecture_unit = lecture_units[0].properties
            lecture_transcription_dto = LectureUnitPageChunkRetrievalDTO(
                uuid=uuid,
                course_id=lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name=lecture_unit[LectureUnitSchema.COURSE_DESCRIPTION.value],
                course_description=lecture_unit[
                    LectureUnitSchema.COURSE_DESCRIPTION.value
                ],
                lecture_id=lecture_page_chunk[
                    LectureUnitPageChunkSchema.LECTURE_ID.value
                ],
                lecture_name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
                lecture_unit_id=lecture_page_chunk[
                    LectureUnitPageChunkSchema.LECTURE_ID.value
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
                page_text_content=lecture_page_chunk[
                    LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value
                ],
                base_url=lecture_page_chunk[LectureUnitPageChunkSchema.BASE_URL.value],
            )
            return lecture_transcription_dto
