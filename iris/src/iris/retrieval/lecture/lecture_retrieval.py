import concurrent.futures
from asyncio.log import logger
from enum import Enum
from typing import List, cast

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from langsmith import traceable
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.message_converters import (
    convert_iris_message_to_langchain_message,
)
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import PyrisMessage
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
    LectureUnitRetrievalDTO,
    LectureUnitSegmentRetrievalDTO,
)
from iris.llm import (
    CompletionArguments,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.request_handler.model_version_request_handler import (
    ModelVersionRequestHandler,
)
from iris.llm.request_handler.rerank_request_handler import (
    RerankRequestHandler,
)
from iris.pipeline.prompts.lecture_retrieval_prompts import (
    lecture_retrieval_initial_prompt_lecture_pages_with_exercise_context,
    lecture_retrieval_initial_prompt_lecture_transcriptions_with_exercise_context,
    lecture_retriever_initial_prompt_lecture_pages,
    lecture_retriever_initial_prompt_lecture_transcriptions,
    rewrite_student_query_prompt,
    rewrite_student_query_prompt_with_exercise_context,
    write_hypothetical_lecture_pages_answer_prompt,
    write_hypothetical_lecture_transcriptions_answer_prompt,
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


class QueryRewriteMode(Enum):
    LECTURE_PAGES = "lecture_pages"
    LECTURE_TRANSCRIPTIONS = "lecture_transcriptions"


class LectureRetrieval(SubPipeline):
    """LectureRetrieval retrieves lecture data from the vector database by processing lecture units, transcriptions,
     and page chunks.

    It combines various sources of lecture-related data and formats them into a single DTO for further processing.
    """

    def __init__(self, client: WeaviateClient):
        super().__init__(implementation_id="lecture_retrieval_pipeline")
        request_handler = ModelVersionRequestHandler(version="gpt-4o-mini")
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.llm_embedding = ModelVersionRequestHandler(
            version="text-embedding-3-small"
        )
        self.pipeline = self.llm | StrOutputParser()

        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.lecture_transcription_collection = init_lecture_transcription_schema(
            client
        )
        self.lecture_unit_page_chunk_collection = init_lecture_unit_page_chunk_schema(
            client
        )

        self.tokens = []

        self.lecture_unit_segment_pipeline = LectureUnitSegmentRetrieval(client)
        self.lecture_transcription_pipeline = LectureTranscriptionRetrieval(client)
        self.lecture_unit_page_chunk_pipeline = LecturePageChunkRetrieval(client)

        self.cohere_client = RerankRequestHandler(model_id="cohere")

    def __call__(
        self,
        query: str,
        course_id: int,
        chat_history: List[PyrisMessage],
        problem_statement: str | None = None,
        exercise_title: str | None = None,
        lecture_id: int | None = None,
        lecture_unit_id: int | None = None,
        base_url: str | None = None,
    ) -> LectureRetrievalDTO:
        lecture_unit = self.get_lecture_unit(course_id, lecture_id, lecture_unit_id)
        if lecture_unit is None:
            return LectureRetrievalDTO(
                lecture_transcriptions=[],
                lecture_unit_page_chunks=[],
                lecture_unit_segments=[],
            )

        (
            rewritten_lecture_pages_query,
            rewritten_lecture_transcriptions_query,
            hypothetical_lecture_pages_answer_query,
            hypothetical_lecture_transcriptions_answer_query,
        ) = self.run_parallel_rewrite_tasks(
            chat_history,
            query,
            lecture_unit.course_language,
            lecture_unit.course_name,
            problem_statement,
            exercise_title,
        )

        (
            lecture_unit_segments,
            lecture_transcriptions,
            lecture_unit_page_chunks,
        ) = self.call_lecture_pipelines(
            lecture_unit,
            query,
            rewritten_lecture_pages_query,
            rewritten_lecture_transcriptions_query,
            hypothetical_lecture_pages_answer_query,
            hypothetical_lecture_transcriptions_answer_query,
        )

        for lecture_unit_segment in lecture_unit_segments:
            lecture_transcriptions += self.get_lecture_transcription_of_lecture_unit(
                lecture_unit_segment
            )
            lecture_unit_page_chunks += self.get_lecture_page_chunks_of_lecture_unit(
                lecture_unit_segment
            )

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

        lecture_transcriptions = self.cohere_client.rerank(
            query,
            lecture_transcriptions,
            top_n=7,
            content_field_name="segment_text",
        )
        lecture_unit_page_chunks = self.cohere_client.rerank(
            query,
            lecture_unit_page_chunks,
            top_n=7,
            content_field_name="page_text_content",
        )

        return LectureRetrievalDTO(
            lecture_unit_segments=lecture_unit_segments,
            lecture_transcriptions=lecture_transcriptions,
            lecture_unit_page_chunks=lecture_unit_page_chunks,
        )

    def get_lecture_unit(
        self,
        course_id: int,
        lecture_id: int | None = None,
        lecture_unit_id: int | None = None,
        base_url: str | None = None,
    ):
        lecture_filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
            course_id
        )

        if base_url is not None:
            lecture_filter &= Filter.by_property(
                LectureUnitSchema.BASE_URL.value
            ).equal(base_url)

        if lecture_id is not None and lecture_unit_id is not None:
            lecture_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_ID.value
            ).equal(lecture_id)
            lecture_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ).equal(lecture_unit_id)

            lecture_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_filter
            ).objects
            if len(lecture_units) == 0:
                return None

            lecture_unit = lecture_units[0].properties
            lecture_unit_uuid = str(lecture_units[0].uuid)

            # Cast Weaviate properties to expected types
            course_id_val = lecture_unit[LectureUnitSchema.COURSE_ID.value]
            if not isinstance(course_id_val, int):
                raise TypeError(
                    f"Expected int for course_id, got {type(course_id_val)}"
                )
            course_name_val = lecture_unit[LectureUnitSchema.COURSE_NAME.value]
            if not isinstance(course_name_val, str):
                raise TypeError(
                    f"Expected str for course_name, got {type(course_name_val)}"
                )
            course_description_val = lecture_unit[
                LectureUnitSchema.COURSE_DESCRIPTION.value
            ]
            if not isinstance(course_description_val, str):
                raise TypeError(
                    f"Expected str for course_description, got {type(course_description_val)}"
                )
            course_language_val = lecture_unit[LectureUnitSchema.COURSE_LANGUAGE.value]
            if not isinstance(course_language_val, str):
                raise TypeError(
                    f"Expected str for course_language, got {type(course_language_val)}"
                )
            lecture_unit_summary_val = lecture_unit[
                LectureUnitSchema.LECTURE_UNIT_SUMMARY.value
            ]
            if not isinstance(lecture_unit_summary_val, str):
                raise TypeError(
                    f"Expected str for lecture_unit_summary, got {type(lecture_unit_summary_val)}"
                )

            lecture_id_val = lecture_unit.get(LectureUnitSchema.LECTURE_ID.value)
            lecture_id_int = (
                cast(int, lecture_id_val) if lecture_id_val is not None else None
            )
            lecture_name_val = lecture_unit.get(
                LectureUnitSchema.LECTURE_UNIT_NAME.value
            )
            lecture_name_str = (
                cast(str, lecture_name_val) if lecture_name_val is not None else None
            )
            lecture_unit_id_val = lecture_unit.get(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            )
            lecture_unit_id_int = (
                cast(int, lecture_unit_id_val)
                if lecture_unit_id_val is not None
                else None
            )
            lecture_unit_name_val = lecture_unit.get(
                LectureUnitSchema.LECTURE_UNIT_NAME.value
            )
            lecture_unit_name_str = (
                cast(str, lecture_unit_name_val)
                if lecture_unit_name_val is not None
                else None
            )
            lecture_unit_link_val = lecture_unit.get(
                LectureUnitSchema.LECTURE_UNIT_LINK.value
            )
            lecture_unit_link_str = (
                cast(str, lecture_unit_link_val)
                if lecture_unit_link_val is not None
                else None
            )
            video_link_val = lecture_unit.get(LectureUnitSchema.VIDEO_LINK.value)
            video_link_str = (
                cast(str, video_link_val) if video_link_val is not None else None
            )

            return LectureUnitRetrievalDTO(
                uuid=lecture_unit_uuid,
                course_id=course_id_val,
                course_name=course_name_val,
                course_description=course_description_val,
                course_language=course_language_val,
                lecture_id=lecture_id_int,
                lecture_name=lecture_name_str,
                lecture_unit_id=lecture_unit_id_int,
                lecture_unit_name=lecture_unit_name_str,
                lecture_unit_link=lecture_unit_link_str,
                video_link=video_link_str,
                base_url=base_url or "",
                lecture_unit_summary=lecture_unit_summary_val,
            )

        elif lecture_id is not None:
            lecture_filter &= Filter.by_property(
                LectureUnitSchema.LECTURE_ID.value
            ).equal(lecture_id)
            lecture_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_filter
            ).objects

            if len(lecture_units) == 0:
                return None

            lecture_unit = lecture_units[0].properties
            lecture_unit_uuid = str(lecture_units[0].uuid)

            # Cast Weaviate properties to expected types
            course_id_val = lecture_unit[LectureUnitSchema.COURSE_ID.value]
            if not isinstance(course_id_val, int):
                raise TypeError(
                    f"Expected int for course_id, got {type(course_id_val)}"
                )
            course_name_val = lecture_unit[LectureUnitSchema.COURSE_NAME.value]
            if not isinstance(course_name_val, str):
                raise TypeError(
                    f"Expected str for course_name, got {type(course_name_val)}"
                )
            course_description_val = lecture_unit[
                LectureUnitSchema.COURSE_DESCRIPTION.value
            ]
            if not isinstance(course_description_val, str):
                raise TypeError(
                    f"Expected str for course_description, got {type(course_description_val)}"
                )
            course_language_val = lecture_unit[LectureUnitSchema.COURSE_LANGUAGE.value]
            if not isinstance(course_language_val, str):
                raise TypeError(
                    f"Expected str for course_language, got {type(course_language_val)}"
                )
            lecture_unit_summary_val = lecture_unit[
                LectureUnitSchema.LECTURE_UNIT_SUMMARY.value
            ]
            if not isinstance(lecture_unit_summary_val, str):
                raise TypeError(
                    f"Expected str for lecture_unit_summary, got {type(lecture_unit_summary_val)}"
                )

            lecture_id_val = lecture_unit.get(LectureUnitSchema.LECTURE_ID.value)
            lecture_id_int = (
                cast(int, lecture_id_val) if lecture_id_val is not None else None
            )
            lecture_name_val = lecture_unit.get(
                LectureUnitSchema.LECTURE_UNIT_NAME.value
            )
            lecture_name_str = (
                cast(str, lecture_name_val) if lecture_name_val is not None else None
            )

            return LectureUnitRetrievalDTO(
                uuid=lecture_unit_uuid,
                course_id=course_id_val,
                course_name=course_name_val,
                course_description=course_description_val,
                course_language=course_language_val,
                lecture_id=lecture_id_int,
                lecture_name=lecture_name_str,
                lecture_unit_id=None,
                lecture_unit_name=None,
                lecture_unit_link=None,
                video_link=None,
                base_url=base_url or "",
                lecture_unit_summary=lecture_unit_summary_val,
            )

        else:
            lecture_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_filter
            ).objects
            if len(lecture_units) == 0:
                return None

            lecture_unit = lecture_units[0].properties
            lecture_unit_uuid = str(lecture_units[0].uuid)

            # Cast Weaviate properties to expected types
            course_id_val = lecture_unit[LectureUnitSchema.COURSE_ID.value]
            if not isinstance(course_id_val, int):
                raise TypeError(
                    f"Expected int for course_id, got {type(course_id_val)}"
                )
            course_name_val = lecture_unit[LectureUnitSchema.COURSE_NAME.value]
            if not isinstance(course_name_val, str):
                raise TypeError(
                    f"Expected str for course_name, got {type(course_name_val)}"
                )
            course_description_val = lecture_unit[
                LectureUnitSchema.COURSE_DESCRIPTION.value
            ]
            if not isinstance(course_description_val, str):
                raise TypeError(
                    f"Expected str for course_description, got {type(course_description_val)}"
                )
            course_language_val = lecture_unit[LectureUnitSchema.COURSE_LANGUAGE.value]
            if not isinstance(course_language_val, str):
                raise TypeError(
                    f"Expected str for course_language, got {type(course_language_val)}"
                )
            lecture_unit_summary_val = lecture_unit[
                LectureUnitSchema.LECTURE_UNIT_SUMMARY.value
            ]
            if not isinstance(lecture_unit_summary_val, str):
                raise TypeError(
                    f"Expected str for lecture_unit_summary, got {type(lecture_unit_summary_val)}"
                )

            return LectureUnitRetrievalDTO(
                uuid=lecture_unit_uuid,
                course_id=course_id_val,
                course_name=course_name_val,
                course_description=course_description_val,
                course_language=course_language_val,
                lecture_id=None,
                lecture_name=None,
                lecture_unit_id=None,
                lecture_unit_name=None,
                lecture_unit_link=None,
                video_link=None,
                base_url=base_url or "",
                lecture_unit_summary=lecture_unit_summary_val,
            )

    @traceable(name="Retrieval: Run Parallel Rewrite Tasks")
    def run_parallel_rewrite_tasks(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        course_language: str,
        course_name: str | None = None,
        problem_statement: str | None = None,
        exercise_title: str | None = None,
    ):
        """
        Run the rewrite tasks in parallel.
        """
        if problem_statement:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Schedule the rewrite tasks to run in parallel
                rewritten_lecture_pages_query_future = executor.submit(
                    self.rewrite_student_query_with_exercise_context,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                    exercise_title,
                    problem_statement,
                    QueryRewriteMode.LECTURE_PAGES,
                )
                rewritten_lecture_transcriptions_query_future = executor.submit(
                    self.rewrite_student_query_with_exercise_context,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                    exercise_title,
                    problem_statement,
                    QueryRewriteMode.LECTURE_TRANSCRIPTIONS,
                )
                hypothetical_lecture_pages_answer_query_future = executor.submit(
                    self.rewrite_elaborated_query_with_exercise_context,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                    exercise_title,
                    problem_statement,
                    QueryRewriteMode.LECTURE_PAGES,
                )
                hypothetical_lecture_transcriptions_answer_query_future = (
                    executor.submit(
                        self.rewrite_elaborated_query_with_exercise_context,
                        chat_history,
                        student_query,
                        course_language,
                        course_name,
                        exercise_title,
                        problem_statement,
                        QueryRewriteMode.LECTURE_TRANSCRIPTIONS,
                    )
                )

                # Get the results once both tasks are complete
                rewritten_lecture_pages_query: str = (
                    rewritten_lecture_pages_query_future.result()
                )
                rewritten_lecture_transcriptions_query: str = (
                    rewritten_lecture_transcriptions_query_future.result()
                )
                hypothetical_lecture_pages_answer_query: str = (
                    hypothetical_lecture_pages_answer_query_future.result()
                )
                hypothetical_lecture_transcriptions_answer_query: str = (
                    hypothetical_lecture_transcriptions_answer_query_future.result()
                )
        else:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Schedule the rewrite tasks to run in parallel
                rewritten_lecture_pages_query_future = executor.submit(
                    self.rewrite_student_query,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                    QueryRewriteMode.LECTURE_PAGES,
                )
                rewritten_lecture_transcriptions_query_future = executor.submit(
                    self.rewrite_student_query,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                    QueryRewriteMode.LECTURE_TRANSCRIPTIONS,
                )
                hypothetical_lecture_pages_answer_query_future = executor.submit(
                    self.rewrite_elaborated_query,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                    QueryRewriteMode.LECTURE_PAGES,
                )
                hypothetical_lecture_transcriptions_answer_query_future = (
                    executor.submit(
                        self.rewrite_elaborated_query,
                        chat_history,
                        student_query,
                        course_language,
                        course_name,
                        QueryRewriteMode.LECTURE_TRANSCRIPTIONS,
                    )
                )

                # Get the results once both tasks are complete
                rewritten_lecture_pages_query = (
                    rewritten_lecture_pages_query_future.result()
                )
                rewritten_lecture_transcriptions_query = (
                    rewritten_lecture_transcriptions_query_future.result()
                )
                hypothetical_lecture_pages_answer_query = (
                    hypothetical_lecture_pages_answer_query_future.result()
                )
                hypothetical_lecture_transcriptions_answer_query = (
                    hypothetical_lecture_transcriptions_answer_query_future.result()
                )

        return (
            rewritten_lecture_pages_query,
            rewritten_lecture_transcriptions_query,
            hypothetical_lecture_pages_answer_query,
            hypothetical_lecture_transcriptions_answer_query,
        )

    @traceable(name="Retrieval: Rewrite Student Query")
    def rewrite_student_query(
        self,
        chat_history: List[PyrisMessage],
        student_query: str,
        course_language: str,
        course_name: str,
        rewrite_mode: QueryRewriteMode,
    ) -> str:
        """
        Rewrite the student query.
        """
        if rewrite_mode == QueryRewriteMode.LECTURE_TRANSCRIPTIONS:
            initial_prompt = lecture_retriever_initial_prompt_lecture_transcriptions
        else:
            initial_prompt = lecture_retriever_initial_prompt_lecture_pages

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", initial_prompt),
            ]
        )
        prompt = self._add_last_four_messages_to_prompt(prompt, chat_history)
        prompt += SystemMessagePromptTemplate.from_template(
            rewrite_student_query_prompt
        )
        prompt_val = prompt.format_messages(
            course_language=course_language,
            course_name=course_name,
            student_query=student_query,
        )
        prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response = (prompt | self.pipeline).invoke({})
            token_usage = self.llm.tokens
            if token_usage is not None:
                token_usage.pipeline = PipelineEnum.IRIS_LECTURE_RETRIEVAL_PIPELINE
                self.tokens.append(token_usage)
            logger.info("Response from exercise chat pipeline: %s", response)
            return response
        except Exception as e:
            raise e

    @traceable(name="Retrieval: Rewrite Student Query with Exercise Context")
    def rewrite_student_query_with_exercise_context(
        self,
        chat_history: List[PyrisMessage],
        student_query: str,
        course_language: str,
        course_name: str,
        exercise_name: str,
        problem_statement: str,
        rewrite_mode: QueryRewriteMode,
    ) -> str:
        """
        Rewrite the student query to generate fitting lecture content and embed it.
        """
        if rewrite_mode == QueryRewriteMode.LECTURE_TRANSCRIPTIONS:
            initial_prompt = lecture_retrieval_initial_prompt_lecture_transcriptions_with_exercise_context
        else:
            initial_prompt = (
                lecture_retrieval_initial_prompt_lecture_pages_with_exercise_context
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", initial_prompt),
            ]
        )
        prompt = self._add_last_four_messages_to_prompt(prompt, chat_history)
        prompt += SystemMessagePromptTemplate.from_template(
            rewrite_student_query_prompt_with_exercise_context
        )
        prompt_val = prompt.format_messages(
            course_language=course_language,
            course_name=course_name,
            exercise_name=exercise_name,
            problem_statement=problem_statement,
            student_query=student_query,
        )
        prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response = (prompt | self.pipeline).invoke({})
            token_usage = self.llm.tokens
            if token_usage is not None:
                token_usage.pipeline = PipelineEnum.IRIS_LECTURE_RETRIEVAL_PIPELINE
                self.tokens.append(token_usage)
            logger.info("Response from exercise chat pipeline: %s", response)
            return response
        except Exception as e:
            raise e

    @traceable(name="Retrieval: Rewrite Elaborated Query")
    def rewrite_elaborated_query(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        course_language: str,
        course_name: str,
        rewrite_mode: QueryRewriteMode,
    ) -> str:
        """
        Rewrite the student query to generate fitting lecture content and embed it.
        To extract more relevant content from the vector database.
        """
        if rewrite_mode == QueryRewriteMode.LECTURE_TRANSCRIPTIONS:
            write_hypothetical_answer_prompt = (
                write_hypothetical_lecture_transcriptions_answer_prompt
            )
        else:
            write_hypothetical_answer_prompt = (
                write_hypothetical_lecture_pages_answer_prompt
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", write_hypothetical_answer_prompt),
            ]
        )
        prompt = self._add_last_four_messages_to_prompt(prompt, chat_history)
        prompt += ChatPromptTemplate.from_messages(
            [
                ("user", student_query),
            ]
        )
        prompt_val = prompt.format_messages(
            course_language=course_language,
            course_name=course_name,
        )
        prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response = (prompt | self.pipeline).invoke({})
            token_usage = self.llm.tokens
            if token_usage is not None:
                token_usage.pipeline = PipelineEnum.IRIS_LECTURE_RETRIEVAL_PIPELINE
                self.tokens.append(token_usage)
            logger.info("Response from retirval pipeline: %s", response)
            return response
        except Exception as e:
            raise e

    @traceable(name="Retrieval: Rewrite Elaborated Query with Exercise Context")
    def rewrite_elaborated_query_with_exercise_context(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        course_language: str,
        course_name: str,
        exercise_name: str,
        problem_statement: str,
        rewrite_mode: QueryRewriteMode,
    ) -> str:
        """
        Rewrite the student query to generate fitting lecture content and embed it.
        To extract more relevant content from the vector database.
        """

        if rewrite_mode == QueryRewriteMode.LECTURE_TRANSCRIPTIONS:
            write_hypothetical_answer_prompt = (
                write_hypothetical_lecture_pages_answer_prompt
            )
        else:
            write_hypothetical_answer_prompt = (
                write_hypothetical_lecture_pages_answer_prompt
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", write_hypothetical_answer_prompt),
            ]
        )
        prompt = self._add_last_four_messages_to_prompt(prompt, chat_history)
        prompt_val = prompt.format_messages(
            course_language=course_language,
            course_name=course_name,
            exercise_name=exercise_name,
            problem_statement=problem_statement,
        )
        prompt = ChatPromptTemplate.from_messages(prompt_val)
        prompt += ChatPromptTemplate.from_messages(
            [
                ("user", student_query),
            ]
        )
        try:
            response = (prompt | self.pipeline).invoke({})
            token_usage = self.llm.tokens
            if token_usage is not None:
                token_usage.pipeline = PipelineEnum.IRIS_LECTURE_RETRIEVAL_PIPELINE
                self.tokens.append(token_usage)
            logger.info("Response from exercise chat pipeline: %s", response)
            return response
        except Exception as e:
            raise e

    def _add_last_four_messages_to_prompt(
        self,
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

    def call_lecture_pipelines(
        self,
        lecture_unit: LectureUnitRetrievalDTO,
        student_query: str,
        lecture_pages_query: str,
        lecture_transcriptions_query: str,
        hypothetical_lecture_pages_answer_query: str,
        hypothetical_lecture_transcriptions_answer_query: str,
    ):
        """
        Call the different pipelines for lecture content retrieval.
        """
        with concurrent.futures.ThreadPoolExecutor() as executor:
            lecture_unit_segments_future = executor.submit(
                self.lecture_unit_segment_pipeline,
                student_query,
                lecture_transcriptions_query,
                hypothetical_lecture_transcriptions_answer_query,
                lecture_unit,
            )
            lecture_transcriptions_future = executor.submit(
                self.lecture_transcription_pipeline,
                student_query,
                lecture_transcriptions_query,
                hypothetical_lecture_transcriptions_answer_query,
                lecture_unit,
            )
            lecture_unit_page_chunks_future = executor.submit(
                self.lecture_unit_page_chunk_pipeline,
                student_query,
                lecture_pages_query,
                hypothetical_lecture_pages_answer_query,
                lecture_unit,
            )

            lecture_unit_segments: List[LectureUnitSegmentRetrievalDTO] = (
                lecture_unit_segments_future.result()
            )
            lecture_transcriptions: List[LectureTranscriptionRetrievalDTO] = (
                lecture_transcriptions_future.result()
            )
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
        ).equal(lecture_unit_segment.page_number)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.BASE_URL.value
        ).equal(lecture_unit_segment.base_url)

        lecture_transcriptions = (
            self.lecture_transcription_collection.query.fetch_objects(
                filters=transcription_filter
            ).objects
        )

        result = []
        for transcription in lecture_transcriptions:
            props = transcription.properties
            language_val = props[LectureTranscriptionSchema.LANGUAGE.value]
            if not isinstance(language_val, str):
                raise TypeError(f"Expected str for language, got {type(language_val)}")
            segment_start_time_val = props[
                LectureTranscriptionSchema.SEGMENT_START_TIME.value
            ]
            if not isinstance(segment_start_time_val, (int, float)):
                raise TypeError(
                    f"Expected int/float for segment_start_time, got {type(segment_start_time_val)}"
                )
            segment_end_time_val = props[
                LectureTranscriptionSchema.SEGMENT_END_TIME.value
            ]
            if not isinstance(segment_end_time_val, (int, float)):
                raise TypeError(
                    f"Expected int/float for segment_end_time, got {type(segment_end_time_val)}"
                )
            page_number_val = props[LectureTranscriptionSchema.PAGE_NUMBER.value]
            if not isinstance(page_number_val, int):
                raise TypeError(
                    f"Expected int for page_number, got {type(page_number_val)}"
                )
            segment_summary_val = props[
                LectureTranscriptionSchema.SEGMENT_SUMMARY.value
            ]
            if not isinstance(segment_summary_val, str):
                raise TypeError(
                    f"Expected str for segment_summary, got {type(segment_summary_val)}"
                )
            segment_text_val = props[LectureTranscriptionSchema.SEGMENT_TEXT.value]
            if not isinstance(segment_text_val, str):
                raise TypeError(
                    f"Expected str for segment_text, got {type(segment_text_val)}"
                )

            result.append(
                LectureTranscriptionRetrievalDTO(
                    uuid=str(transcription.uuid),
                    course_id=lecture_unit_segment.course_id,
                    course_name=lecture_unit_segment.course_name,
                    course_description=lecture_unit_segment.course_description,
                    lecture_id=lecture_unit_segment.lecture_id,
                    lecture_name=lecture_unit_segment.lecture_name,
                    lecture_unit_id=lecture_unit_segment.lecture_unit_id,
                    lecture_unit_name=lecture_unit_segment.lecture_unit_name,
                    video_link=lecture_unit_segment.video_link,
                    language=language_val,
                    segment_start_time=float(segment_start_time_val),
                    segment_end_time=float(segment_end_time_val),
                    page_number=page_number_val,
                    segment_summary=segment_summary_val,
                    segment_text=segment_text_val,
                    base_url=lecture_unit_segment.base_url,
                )
            )
        return result

    def get_lecture_page_chunks_of_lecture_unit(
        self, lecture_unit_segment: LectureUnitSegmentRetrievalDTO
    ):
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
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.BASE_URL.value
        ).equal(lecture_unit_segment.base_url)

        lecture_page_chunks = (
            self.lecture_unit_page_chunk_collection.query.fetch_objects(
                filters=page_chunk_filter
            ).objects
        )

        result = []
        for chunk in lecture_page_chunks:
            props = chunk.properties
            course_language_val = props[
                LectureUnitPageChunkSchema.COURSE_LANGUAGE.value
            ]
            if not isinstance(course_language_val, str):
                raise TypeError(
                    f"Expected str for course_language, got {type(course_language_val)}"
                )
            page_number_val = props[LectureUnitPageChunkSchema.PAGE_NUMBER.value]
            if not isinstance(page_number_val, int):
                raise TypeError(
                    f"Expected int for page_number, got {type(page_number_val)}"
                )
            page_text_content_val = props[
                LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value
            ]
            if not isinstance(page_text_content_val, str):
                raise TypeError(
                    f"Expected str for page_text_content, got {type(page_text_content_val)}"
                )

            result.append(
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
                    course_language_val,
                    page_number_val,
                    page_text_content_val,
                    lecture_unit_segment.base_url,
                )
            )
        return result
