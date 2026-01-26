import concurrent.futures
from abc import ABC, abstractmethod
from typing import List, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.tracing import observe

from ..common.message_converters import (
    convert_iris_message_to_langchain_message,
)
from ..common.pyris_message import PyrisMessage
from ..llm.langchain import IrisLangchainChatModel
from ..pipeline.sub_pipeline import SubPipeline

logger = get_logger(__name__)


def merge_retrieved_chunks(
    basic_retrieved_faq_chunks, hyde_retrieved_faq_chunks
) -> List[dict]:
    """
    Merge the retrieved chunks from the basic and hyde retrieval methods. This function ensures that for any
    duplicate IDs, the properties from hyde_retrieved_faq_chunks will overwrite those from
    basic_retrieved_faq_chunks.
    """
    merged_chunks = {}
    for chunk in basic_retrieved_faq_chunks:
        merged_chunks[chunk["id"]] = chunk["properties"]

    for chunk in hyde_retrieved_faq_chunks:
        merged_chunks[chunk["id"]] = chunk["properties"]

    return [properties for uuid, properties in merged_chunks.items()]


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


class BaseRetrieval(SubPipeline, ABC):
    """
    Base class for retrieval pipelines.
    """

    tokens: List[TokenUsageDTO]

    @abstractmethod
    def __call__(self, *args, **kwargs):
        """Muss in der konkreten Implementierung überschrieben werden"""

    def __init__(
        self, client: WeaviateClient, schema_init_func, local: bool = False, **kwargs
    ):
        super().__init__(
            implementation_id=kwargs.get("implementation_id", "base_retrieval_pipeline")
        )
        request_handler = ModelVersionRequestHandler(
            version="llama3.3:latest" if local else "gpt-4.1-mini"
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.llm_embedding = ModelVersionRequestHandler("text-embedding-3-small")
        self.pipeline = self.llm | StrOutputParser()
        self.collection = schema_init_func(client)
        self.tokens = []

    @observe(name="Retrieval: Question Assessment")
    def assess_question(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        assessment_prompt: str,
        assessment_prompt_final: str,
    ) -> bool:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", assessment_prompt),
            ]
        )
        prompt = _add_last_four_messages_to_prompt(prompt, chat_history)
        # Escape curly braces in student_query for LangChain template compatibility
        safe_query = student_query.replace("{", "{{").replace("}", "}}")
        prompt += ChatPromptTemplate.from_messages(
            [
                ("user", safe_query),
            ]
        )
        prompt += ChatPromptTemplate.from_messages(
            [
                ("system", assessment_prompt_final),
            ]
        )

        try:
            response = (prompt | self.pipeline).invoke({})
            logger.debug("Assessment completed | result=%s", response)
            return response == "YES"
        except Exception as e:
            raise e

    @observe(name="Retrieval: Rewrite Student Query")
    def rewrite_student_query(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        course_language: str,
        course_name: str,
        initial_prompt: str,
        rewrite_prompt: str,
        pipeline_enum: PipelineEnum,
    ) -> str:
        """
        Rewrite the student query.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", initial_prompt),
            ]
        )
        prompt = _add_last_four_messages_to_prompt(prompt, chat_history)
        prompt += SystemMessagePromptTemplate.from_template(rewrite_prompt)
        prompt_val = prompt.format_messages(
            course_language=course_language,
            course_name=course_name,
            student_query=student_query,
        )
        prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response = (prompt | self.pipeline).invoke({})
            token_usage = self.llm.tokens
            token_usage.pipeline = pipeline_enum
            self.tokens.append(self.llm.tokens)
            return response
        except Exception as e:
            raise e

    @observe(name="Retrieval: Search in DB")
    def search_in_db(
        self,
        query: str,
        hybrid_factor: float,
        result_limit: int,
        schema_properties: List[str],
        course_id: Optional[int] = None,
        base_url: Optional[str] = None,
        course_id_property: str = "course_id",
        base_url_property: str = "base_url",
    ):
        """
        Search the database for the given query.
        """
        logger.info("[BASIC_RETRIEVAL] Searching in the database for query: %s", query)
        filter_weaviate = None

        if course_id:
            filter_weaviate = Filter.by_property(course_id_property).equal(course_id)
            if base_url:
                filter_weaviate &= Filter.by_property(base_url_property).equal(base_url)

        vec = self.llm_embedding.embed(query)
        return self.collection.query.hybrid(
            query=query,
            alpha=hybrid_factor,
            vector=vec,
            return_properties=schema_properties,
            limit=result_limit,
            filters=filter_weaviate,
        )

    @observe(name="Retrieval: Run Parallel Rewrite Tasks")
    def run_parallel_rewrite_tasks(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        result_limit: int,
        course_language: str,
        initial_prompt: str,
        rewrite_prompt: str,
        hypothetical_answer_prompt: str,
        pipeline_enum: PipelineEnum,
        course_name: Optional[str] = None,
        course_id: Optional[int] = None,
        base_url: Optional[str] = None,
        # problem_statement: Optional[str] = None,
        # exercise_title: Optional[str] = None,
    ):
        """
        Run the rewrite tasks in parallel.
        """
        with concurrent.futures.ThreadPoolExecutor() as executor:
            rewritten_query_future = executor.submit(
                self.rewrite_student_query,
                chat_history,
                student_query,
                course_language,
                course_name,
                initial_prompt,
                rewrite_prompt,
                pipeline_enum,
            )
            hypothetical_answer_query_future = executor.submit(
                self.rewrite_student_query,
                chat_history,
                student_query,
                course_language,
                course_name,
                initial_prompt,
                hypothetical_answer_prompt,
                pipeline_enum,
            )

            rewritten_query = rewritten_query_future.result()
            hypothetical_answer_query = hypothetical_answer_query_future.result()

        with concurrent.futures.ThreadPoolExecutor() as executor:
            response_future = executor.submit(
                self.search_in_db,
                query=rewritten_query,
                hybrid_factor=0.9,
                result_limit=result_limit,
                schema_properties=self.get_schema_properties(),
                course_id=course_id,
                base_url=base_url,
            )
            response_hyde_future = executor.submit(
                self.search_in_db,
                query=hypothetical_answer_query,
                hybrid_factor=0.9,
                result_limit=result_limit,
                schema_properties=self.get_schema_properties(),
                course_id=course_id,
                base_url=base_url,
            )

            response = response_future.result()
            response_hyde = response_hyde_future.result()

        return response, response_hyde

    @abstractmethod
    def get_schema_properties(self) -> List[str]:
        """
        Abstract method to be implemented by subclasses to return the schema properties.
        """
        raise NotImplementedError

    def fetch_course_language(
        self, course_id: int, course_language_property: str = "course_language"
    ) -> str:
        """
        Fetch the language of the course based on the course ID.
        If no specific language is set, it defaults to English.
        """
        course_language = "english"

        if course_id:
            result = self.collection.query.fetch_objects(
                filters=Filter.by_property("course_id").equal(course_id),
                limit=1,
                return_properties=[course_language_property],
            )

            if result.objects:
                fetched_language = result.objects[0].properties.get(
                    course_language_property
                )
                if fetched_language:
                    course_language = fetched_language

        return course_language
