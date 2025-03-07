from asyncio.log import logger
from typing import List
import concurrent.futures

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langsmith import traceable
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from app.common.PipelineEnum import PipelineEnum
from app.common.message_converters import convert_iris_message_to_langchain_message

from app.common.pyris_message import PyrisMessage
from app.domain.retrieval.lecture.lecture_retrieval_dto import LectureUnitRetrievalDTO
from app.llm import (
    CapabilityRequestHandler,
    RequirementList,
    CompletionArguments,
    BasicRequestHandler,
)
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline
from app.pipeline.prompts.lecture_retrieval_prompts import (
    lecture_retriever_initial_prompt,
    rewrite_student_query_prompt,
    lecture_retrieval_initial_prompt_with_exercise_context,
    rewrite_student_query_prompt_with_exercise_context,
    write_hypothetical_answer_prompt,
    write_hypothetical_answer_with_exercise_context_prompt,
)
from app.pipeline.shared.reranker_pipeline import RerankerPipeline
from app.vector_database.lecture_unit_schema import (
    init_lecture_unit_schema,
    LectureUnitSchema,
)


class LectureRetrieval(Pipeline):
    def __init__(self, client: WeaviateClient):
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
        self.pipeline = self.llm | StrOutputParser()
        self.collection = init_lecture_unit_schema(client)
        self.reranker_pipeline = RerankerPipeline()
        self.tokens = []

    def __call__(
        self,
        query: str,
        course_id: int,
        chat_history: List[PyrisMessage],
        problem_statement: str = None,
        exercise_title: str = None,
        lecture_id: int = None,
        lecture_unit_id: int = None,
        base_url: str = None,
    ):
        print("LectureRetrieval is running")

        lecture_unit = self.get_lecture_unit(course_id, lecture_id, lecture_unit_id)
        if lecture_unit is None:
            raise ValueError("The lecture unit is not indexed")

        rewritten_query, hypothetical_answer_query = self.run_parallel_rewrite_tasks(
            chat_history,
            query,
            lecture_unit.course_language,
            lecture_unit.course_name,
            problem_statement,
            exercise_title,
        )

        print("Doneeee------")
        print(rewritten_query)
        print("Hypo:")
        print(hypothetical_answer_query)

        # 0. LectureUnit bauen/fetchen
        # 1. User Query rewrite -> Chat History hinzufügen?
        # 2. Einzelne Pipelines aufrufen
        # 3. Ergebnisse mergen & duplikate entfernen

        return self

    def get_lecture_unit(
        self,
        course_id: int,
        lecture_id: int = None,
        lecture_unit_id: int = None,
        base_url: str = None,
    ):

        if lecture_id is not None and lecture_unit_id is not None:
            filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                course_id
            )
            filter &= Filter.by_property(LectureUnitSchema.LECTURE_ID.value).equal(
                lecture_id
            )
            filter &= Filter.by_property(LectureUnitSchema.LECTURE_UNIT_ID.value).equal(
                lecture_unit_id
            )
            if base_url:
                filter &= Filter.by_property(LectureUnitSchema.BASE_URL.value).equal(
                    base_url
                )
            lecture_units = self.collection.query.fetch_objects(filters=filter).objects
            if len(lecture_units) == 0:
                return None

            lecture_unit = lecture_units[0].properties

            return LectureUnitRetrievalDTO(
                course_id=lecture_unit.course_id,
                course_name=lecture_unit.course_name,
                course_description=lecture_unit.course_description,
                course_language=lecture_unit.course_language,
                lecture_id=lecture_unit.lecture_id,
                lecture_name=lecture_unit.lecture_name,
                lecture_unit_id=lecture_unit.lecture_unit_id,
                lecture_unit_name=lecture_unit.lecture_unit_name,
                lecture_unit_link=lecture_unit.lecture_unit_link,
                base_url=lecture_unit.base_url,
                lecture_unit_summary=lecture_unit.lecture_unit_summary,
            )

        elif lecture_id is not None:
            filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                course_id
            )
            filter &= Filter.by_property(LectureUnitSchema.LECTURE_ID.value).equal(
                lecture_id
            )
            if base_url:
                filter &= Filter.by_property(LectureUnitSchema.BASE_URL.value).equal(
                    base_url
                )
            lecture_units = self.collection.query.fetch_objects(filters=filter).objects
            if len(lecture_units) == 0:
                return None
            lecture_unit = lecture_units[0].properties
            return LectureUnitRetrievalDTO(
                course_id=lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name=lecture_unit[LectureUnitSchema.COURSE_NAME.value],
                course_description=lecture_unit[LectureUnitSchema.COURSE_DESCRIPTION.value],
                course_language=lecture_unit[LectureUnitSchema.COURSE_LANGUAGE.value],
                lecture_id=lecture_unit[LectureUnitSchema.LECTURE_UNIT_ID.value],
                lecture_name=lecture_unit[LectureUnitSchema.LECTURE_UNIT_NAME.value],
                lecture_unit_id=None,
                lecture_unit_name=None,
                lecture_unit_link=None,
                base_url=base_url,
                lecture_unit_summary=lecture_unit[LectureUnitSchema.LECTURE_UNIT_SUMMARY.value],
            )

        else:
            filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                course_id
            )
            if base_url:
                filter &= Filter.by_property(LectureUnitSchema.BASE_URL.value).equal(
                    base_url
                )
            lecture_units = self.collection.query.fetch_objects(filters=filter).objects
            if len(lecture_units) == 0:
                return None
            lecture_unit = lecture_units[0].properties

            print(lecture_unit)

            return LectureUnitRetrievalDTO(
                course_id=lecture_unit[LectureUnitSchema.COURSE_ID.value],
                course_name=lecture_unit[LectureUnitSchema.COURSE_NAME.value],
                course_description=lecture_unit[LectureUnitSchema.COURSE_DESCRIPTION.value],
                course_language=lecture_unit[LectureUnitSchema.COURSE_LANGUAGE.value],
                lecture_id=None,
                lecture_name=None,
                lecture_unit_id=None,
                lecture_unit_name=None,
                lecture_unit_link=None,
                base_url=base_url,
                lecture_unit_summary=lecture_unit[LectureUnitSchema.LECTURE_UNIT_SUMMARY.value],
            )

    @traceable(name="Retrieval: Run Parallel Rewrite Tasks")
    def run_parallel_rewrite_tasks(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        course_language: str,
        course_name: str = None,
        problem_statement: str = None,
        exercise_title: str = None,
    ):
        """
        Run the rewrite tasks in parallel.
        """
        if problem_statement:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Schedule the rewrite tasks to run in parallel
                rewritten_query_future = executor.submit(
                    self.rewrite_student_query_with_exercise_context,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                    exercise_title,
                    problem_statement,
                )
                hypothetical_answer_query_future = executor.submit(
                    self.rewrite_elaborated_query_with_exercise_context,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                    exercise_title,
                    problem_statement,
                )

                # Get the results once both tasks are complete
                rewritten_query: str = rewritten_query_future.result()
                hypothetical_answer_query: str = (
                    hypothetical_answer_query_future.result()
                )
        else:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Schedule the rewrite tasks to run in parallel
                rewritten_query_future = executor.submit(
                    self.rewrite_student_query,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                )
                hypothetical_answer_query_future = executor.submit(
                    self.rewrite_elaborated_query,
                    chat_history,
                    student_query,
                    course_language,
                    course_name,
                )

                # Get the results once both tasks are complete
                rewritten_query = rewritten_query_future.result()
                hypothetical_answer_query = hypothetical_answer_query_future.result()

        return rewritten_query, hypothetical_answer_query

    @traceable(name="Retrieval: Rewrite Student Query")
    def rewrite_student_query(
        self,
        chat_history: List[PyrisMessage],
        student_query: str,
        course_language: str,
        course_name: str,
    ) -> str:
        """
        Rewrite the student query.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", lecture_retriever_initial_prompt),
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
            token_usage.pipeline = PipelineEnum.IRIS_LECTURE_RETRIEVAL_PIPELINE
            self.tokens.append(self.llm.tokens)
            logger.info(f"Response from exercise chat pipeline: {response}")
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
    ) -> str:
        """
        Rewrite the student query to generate fitting lecture content and embed it.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", lecture_retrieval_initial_prompt_with_exercise_context),
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
            token_usage.pipeline = PipelineEnum.IRIS_LECTURE_RETRIEVAL_PIPELINE
            self.tokens.append(self.llm.tokens)
            logger.info(f"Response from exercise chat pipeline: {response}")
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
    ) -> str:
        """
        Rewrite the student query to generate fitting lecture content and embed it.
        To extract more relevant content from the vector database.
        """
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
            token_usage.pipeline = PipelineEnum.IRIS_LECTURE_RETRIEVAL_PIPELINE
            self.tokens.append(self.llm.tokens)
            logger.info(f"Response from retirval pipeline: {response}")
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
    ) -> str:
        """
        Rewrite the student query to generate fitting lecture content and embed it.
        To extract more relevant content from the vector database.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", write_hypothetical_answer_with_exercise_context_prompt),
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
            token_usage.pipeline = PipelineEnum.IRIS_LECTURE_RETRIEVAL_PIPELINE
            self.tokens.append(self.llm.tokens)
            logger.info(f"Response from exercise chat pipeline: {response}")
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
