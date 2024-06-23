from asyncio.log import logger
from typing import List

from langsmith import traceable
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from ..common import convert_iris_message_to_langchain_message
from ..llm.langchain import IrisLangchainChatModel
from ..pipeline import Pipeline

from app.domain import PyrisMessage
from app.llm import (
    BasicRequestHandler,
    CompletionArguments,
    CapabilityRequestHandler,
    RequirementList,
)
from app.pipeline.shared.reranker_pipeline import RerankerPipeline
from app.vector_database.lecture_schema import init_lecture_schema, LectureSchema
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)

from ..pipeline.prompts.lecture_retrieval_prompts import (
    assessment_prompt,
    assessment_prompt_final,
    rewrite_student_query_prompt,
    lecture_retriever_initial_prompt,
    write_hypothetical_answer_prompt,
    lecture_retrieval_initial_prompt_with_exercise_context,
    rewrite_student_query_prompt_with_exercise_context,
    write_hypothetical_answer_with_exercise_context_prompt,
)
import concurrent.futures


def merge_retrieved_chunks(
    basic_retrieved_lecture_chunks, hyde_retrieved_lecture_chunks
) -> List[dict]:
    """
    Merge the retrieved chunks from the basic and hyde retrieval methods. This function ensures that for any
    duplicate IDs, the properties from hyde_retrieved_lecture_chunks will overwrite those from
    basic_retrieved_lecture_chunks.
    """
    merged_chunks = {}
    for chunk in basic_retrieved_lecture_chunks:
        merged_chunks[chunk["id"]] = chunk["properties"]

    for chunk in hyde_retrieved_lecture_chunks:
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


class LectureRetrieval(Pipeline):
    """
    Class for retrieving lecture data from the database.
    """

    def __init__(self, client: WeaviateClient, **kwargs):
        super().__init__(implementation_id="lecture_retrieval_pipeline")
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=3.5,
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
        self.collection = init_lecture_schema(client)
        self.reranker_pipeline = RerankerPipeline()

    @traceable(name="Full Lecture Retrieval")
    def __call__(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        result_limit: int,
        course_name: str = None,
        course_id: int = None,
        base_url: str = None,
        problem_statement: str = None,
        exercise_title: str = None,
    ) -> List[dict]:
        """
        Retrieve lecture data from the database.
        """
        course_language = self.fetch_course_language(course_id)

        response, response_hyde = self.run_parallel_rewrite_tasks(
            chat_history=chat_history,
            student_query=student_query,
            result_limit=result_limit,
            course_language=course_language,
            course_name=course_name,
            course_id=course_id,
            base_url=base_url,
            problem_statement=problem_statement,
            exercise_title=exercise_title,
        )

        basic_retrieved_lecture_chunks: list[dict[str, dict]] = [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in response.objects
        ]
        hyde_retrieved_lecture_chunks: list[dict[str, dict]] = [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in response_hyde.objects
        ]
        merged_chunks = merge_retrieved_chunks(
            basic_retrieved_lecture_chunks, hyde_retrieved_lecture_chunks
        )
        if len(merged_chunks) != 0:
            selected_chunks_index = self.reranker_pipeline(
                paragraphs=merged_chunks, query=student_query, chat_history=chat_history
            )
            return [merged_chunks[int(i)] for i in selected_chunks_index]
        return []

    @traceable(name="Basic Lecture Retrieval")
    def basic_lecture_retrieval(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        result_limit: int,
        course_name: str = None,
        course_id: int = None,
        base_url: str = None,
    ) -> list[dict[str, dict]]:
        """
        Basic retrieval for pipelines thaat need performance and fast answers.
        """
        if not self.assess_question(chat_history, student_query):
            return []

        rewritten_query = self.rewrite_student_query(
            chat_history, student_query, "course_language", course_name
        )
        response = self.search_in_db(
            query=rewritten_query,
            hybrid_factor=0.9,
            result_limit=result_limit,
            course_id=course_id,
            base_url=base_url,
        )

        basic_retrieved_lecture_chunks: list[dict[str, dict]] = [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in response.objects
        ]
        return basic_retrieved_lecture_chunks

    @traceable(name="Retrieval: Question Assessment")
    def assess_question(
        self, chat_history: list[PyrisMessage], student_query: str
    ) -> bool:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", assessment_prompt),
            ]
        )
        prompt = _add_last_four_messages_to_prompt(prompt, chat_history)
        prompt += ChatPromptTemplate.from_messages(
            [
                ("user", student_query),
            ]
        )
        prompt += ChatPromptTemplate.from_messages(
            [
                ("system", assessment_prompt_final),
            ]
        )

        try:
            response = (prompt | self.pipeline).invoke({})
            logger.info(f"Response from assessment pipeline: {response}")
            return response == "YES"
        except Exception as e:
            raise e

    @traceable(name="Retrieval: Rewrite Student Query")
    def rewrite_student_query(
        self,
        chat_history: list[PyrisMessage],
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
        prompt = _add_last_four_messages_to_prompt(prompt, chat_history)
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
            logger.info(f"Response from exercise chat pipeline: {response}")
            return response
        except Exception as e:
            raise e

    @traceable(name="Retrieval: Rewrite Student Query with Exercise Context")
    def rewrite_student_query_with_exercise_context(
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
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", lecture_retrieval_initial_prompt_with_exercise_context),
            ]
        )
        prompt = _add_last_four_messages_to_prompt(prompt, chat_history)
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
        prompt = _add_last_four_messages_to_prompt(prompt, chat_history)
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
        prompt = _add_last_four_messages_to_prompt(prompt, chat_history)
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
            logger.info(f"Response from exercise chat pipeline: {response}")
            return response
        except Exception as e:
            raise e

    @traceable(name="Retrieval: Search in DB")
    def search_in_db(
        self,
        query: str,
        hybrid_factor: float,
        result_limit: int,
        course_id: int = None,
        base_url: str = None,
    ):
        """
        Search the database for the given query.
        """
        logger.info(f"Searching in the database for query: {query}")
        # Initialize filter to None by default
        filter_weaviate = None

        # Check if course_id is provided
        if course_id:
            # Create a filter for course_id
            filter_weaviate = Filter.by_property(LectureSchema.COURSE_ID.value).equal(
                course_id
            )

            # Extend the filter based on the presence of base_url
            if base_url:
                filter_weaviate &= Filter.by_property(
                    LectureSchema.BASE_URL.value
                ).equal(base_url)

        vec = self.llm_embedding.embed(query)
        return_value = self.collection.query.hybrid(
            query=query,
            alpha=hybrid_factor,
            vector=vec,
            return_properties=[
                LectureSchema.PAGE_TEXT_CONTENT.value,
                LectureSchema.COURSE_NAME.value,
                LectureSchema.LECTURE_NAME.value,
                LectureSchema.PAGE_NUMBER.value,
                LectureSchema.COURSE_ID.value,
            ],
            limit=result_limit,
            filters=filter_weaviate,
        )
        return return_value

    @traceable(name="Retrieval: Run Parallel Rewrite Tasks")
    def run_parallel_rewrite_tasks(
        self,
        chat_history: list[PyrisMessage],
        student_query: str,
        result_limit: int,
        course_language: str,
        course_name: str = None,
        course_id: int = None,
        base_url: str = None,
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

            # Execute the database search tasks
        with concurrent.futures.ThreadPoolExecutor() as executor:
            response_future = executor.submit(
                self.search_in_db,
                query=rewritten_query,
                hybrid_factor=0.7,
                result_limit=result_limit,
                course_id=course_id,
                base_url=base_url,
            )
            response_hyde_future = executor.submit(
                self.search_in_db,
                query=hypothetical_answer_query,
                hybrid_factor=0.9,
                result_limit=result_limit,
                course_id=course_id,
                base_url=base_url,
            )

            # Get the results once both tasks are complete
            response = response_future.result()
            response_hyde = response_hyde_future.result()

        return response, response_hyde

    def fetch_course_language(self, course_id):
        """
        Fetch the language of the course based on the course ID.
        If no specific language is set, it defaults to English.
        """
        course_language = "english"

        if course_id:
            # Fetch the first object that matches the course ID with the language property
            result = self.collection.query.fetch_objects(
                filters=Filter.by_property(LectureSchema.COURSE_ID.value).equal(
                    course_id
                ),
                limit=1,  # We only need one object to check and retrieve the language
                return_properties=[LectureSchema.COURSE_LANGUAGE.value],
            )

            # Check if the result has objects and retrieve the language
            if result.objects:
                fetched_language = result.objects[0].properties.get(
                    LectureSchema.COURSE_LANGUAGE.value
                )
                if fetched_language:
                    course_language = fetched_language

        return course_language
