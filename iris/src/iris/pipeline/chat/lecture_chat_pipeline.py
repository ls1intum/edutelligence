import logging
from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.retrieval.lecture.lecture_page_chunk_retrieval import (
    LecturePageChunkRetrieval,
)

from ...common.message_converters import convert_iris_message_to_langchain_message
from ...common.pyris_message import PyrisMessage
from ...domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)
from ...llm import CapabilityRequestHandler, CompletionArguments, RequirementList
from ...llm.langchain import IrisLangchainChatModel
from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_unit_page_chunk_schema import LectureUnitPageChunkSchema
from ...web.status.status_update import LectureChatCallback
from ..pipeline import Pipeline
from ..shared.citation_pipeline import CitationPipeline

logger = logging.getLogger(__name__)


def chat_history_system_prompt():
    """
    Returns the system prompt for the chat history
    """
    return """This is the chat history of your conversation with the student so far. Read it so you
    know what already happened, but never re-use any message you already wrote. Instead, always write new and original
    responses. The student can reference the messages you've already written."""


def lecture_initial_prompt():
    """
    Returns the initial prompt for the lecture chat
    """
    return """You're Iris, the AI programming tutor integrated into Artemis, the online learning platform of the
     Technical University of Munich (TUM). You are a guide and an educator. Your main goal is to answer the student's
     questions about the lectures. To answer them the best way, relevant lecture content is provided to you with the
     student's question. If the context provided to you is not enough to formulate an answer to the student question
     you can simply ask the student to elaborate more on his question. Use only the parts of the context provided for
     you that is relevant to the student's question. If the user greets you greet him back,
      and ask him how you can help.
     Always formulate your answer in the same language as the user's language.
     """


class LectureChatPipeline(Pipeline):
    """LectureChatPipeline orchestrates the interaction for lecture-based chat queries.

    It uses an IrisLangchainChatModel to generate responses based on a student's question, incorporates chat history and
    relevant lecture content, and returns a final response enriched with citations.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate
    callback: LectureChatCallback

    def __init__(
        self,
        callback: LectureChatCallback,
        dto: LectureChatPipelineExecutionDTO,
        variant: str,
    ):
        super().__init__(implementation_id="lecture_chat_pipeline")
        # Set the langchain chat model
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
                privacy_compliance=True,
            )
        )

        self.callback = callback
        self.dto = dto
        self.variant = variant

        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        # Create the pipelines
        self.db = VectorDatabase()
        self.retriever = LecturePageChunkRetrieval(self.db.client)
        self.pipeline = self.llm | StrOutputParser()
        self.citation_pipeline = CitationPipeline()
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Lecture Chat Pipeline")
    def __call__(self, dto: LectureChatPipelineExecutionDTO):
        """
        Runs the pipeline
        :param dto:  execution data transfer object
        """
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", lecture_initial_prompt()),
                ("system", chat_history_system_prompt()),
            ]
        )
        logger.info("Running lecture chat pipeline...")
        history: List[PyrisMessage] = dto.chat_history[:-1]
        query: PyrisMessage = dto.chat_history[-1]

        self._add_conversation_to_prompt(history, query)

        retrieved_lecture_chunks = self.retriever(
            chat_history=history,
            student_query=query.contents[0].text_content,
            result_limit=5,
            course_name=dto.course.name,
            course_id=dto.course.id,
            base_url=dto.settings.artemis_base_url,
        )

        self._add_relevant_chunks_to_prompt(retrieved_lecture_chunks)
        prompt_val = self.prompt.format_messages()
        self.prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response = (self.prompt | self.pipeline).invoke({})
            self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_CHAT_LECTURE_MESSAGE)
            response_with_citation = self.citation_pipeline(
                retrieved_lecture_chunks, response
            )
            self.tokens.extend(self.citation_pipeline.tokens)
            logger.info("Response from lecture chat pipeline: %s", response)
            self.callback.done(
                "Response created",
                final_result=response_with_citation,
                tokens=self.tokens,
            )
        except Exception as e:
            self.callback.error(
                "Generating interaction suggestions failed.",
                exception=e,
                tokens=self.tokens,
            )
            raise e

    def _add_conversation_to_prompt(
        self,
        chat_history: List[PyrisMessage],
        user_question: PyrisMessage,
    ):
        """
        Adds the chat history and user question to the prompt
            :param chat_history: The chat history
            :param user_question: The user question
            :return: The prompt with the chat history
        """
        if chat_history is not None and len(chat_history) > 0:
            chat_history_messages = [
                convert_iris_message_to_langchain_message(message)
                for message in chat_history
            ]
            self.prompt += chat_history_messages
            self.prompt += SystemMessagePromptTemplate.from_template(
                "Now, consider the student's newest and latest input:"
            )
        self.prompt += convert_iris_message_to_langchain_message(user_question)

    def _add_relevant_chunks_to_prompt(self, retrieved_lecture_chunks: List[dict]):
        """
        Adds the relevant chunks of the lecture to the prompt
        :param retrieved_lecture_chunks: The retrieved lecture chunks
        """
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Next you will find the relevant lecture content:\n"
        )
        for _, chunk in enumerate(retrieved_lecture_chunks):
            text_content_msg = f" \n {chunk.get(LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value)} \n"
            text_content_msg = text_content_msg.replace("{", "{{").replace("}", "}}")
            self.prompt += SystemMessagePromptTemplate.from_template(text_content_msg)
        self.prompt += SystemMessagePromptTemplate.from_template(
            "USE ONLY THE CONTENT YOU NEED TO ANSWER THE QUESTION:\n"
        )
