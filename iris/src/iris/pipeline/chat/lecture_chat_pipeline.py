import logging
import traceback
from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)

from ...common.message_converters import (
    convert_iris_message_to_langchain_message,
)
from ...common.pipeline_enum import PipelineEnum
from ...common.pyris_message import PyrisMessage
from ...domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)
from ...domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
)
from ...domain.variant.lecture_chat_variant import LectureChatVariant
from ...llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...vector_database.database import VectorDatabase
from ...web.status.status_update import LectureChatCallback
from ..pipeline import Pipeline
from ..shared.citation_pipeline import CitationPipeline
from ..shared.utils import (
    format_custom_instructions,
)

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
     questions about the lectures. To provide the best possible answer, the following relevant lecture content is
     provided to you: lecture slides, lecture transcriptions, and lecture segments. Lecture segments contain a
     combined summary of a section of lecture slides and transcription content.
     student's question. If the context provided to you is not enough to formulate an answer to the student question
     you can simply ask the student to elaborate more on his question. Use only the parts of the context provided for
     you that is relevant to the student's question. If the user greets you greet him back,
     and ask him how you can help.
     Always respond in the same language as the user. If they use English, you use English.
     If they use German, you use German, but then always use "du" instead of "Sie".
     """


class LectureChatPipeline(Pipeline[LectureChatVariant]):
    """LectureChatPipeline orchestrates the interaction for lecture-based chat queries.

    It uses an IrisLangchainChatModel to generate responses based on a student's question, incorporates chat history and
    relevant lecture content, and returns a final response enriched with citations.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate
    session_title_pipeline: SessionTitleGenerationPipeline
    callback: LectureChatCallback
    variant: str

    def __init__(
        self,
        callback: LectureChatCallback,
        dto: LectureChatPipelineExecutionDTO,
        variant: str = "default",
    ):
        super().__init__(implementation_id="lecture_chat_pipeline")

        self.callback = callback
        self.dto = dto
        self.variant = variant

        completion_args = CompletionArguments(temperature=0, max_tokens=2000)

        if variant == "advanced":
            model = "gpt-4.1"
        else:
            model = "gpt-4.1-mini"

        request_handler = ModelVersionRequestHandler(version=model)

        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        # Create the pipelines
        self.db = VectorDatabase()
        self.retriever = LectureRetrieval(self.db.client)
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.pipeline = self.llm | StrOutputParser()
        self.citation_pipeline = CitationPipeline()
        self.tokens = []

    @classmethod
    def get_variants(cls) -> List[LectureChatVariant]:
        return [
            LectureChatVariant(
                variant_id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="gpt-4.1-mini",
                citation_model="gpt-4.1-nano",
            ),
            LectureChatVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="gpt-4.1",
                citation_model="gpt-4.1-mini",
            ),
        ]

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

        self.lecture_content = self.retriever(
            query=query.contents[0].text_content,
            course_id=dto.course_id,
            chat_history=history,
            lecture_id=dto.lecture_id,
            lecture_unit_id=dto.lecture_unit_id,
            base_url=dto.settings.artemis_base_url,
        )

        self._add_lecture_content_to_prompt(self.lecture_content)
        custom_instructions = format_custom_instructions(
            custom_instructions=dto.custom_instructions
        )
        if custom_instructions:
            self.prompt += SystemMessagePromptTemplate.from_template(
                custom_instructions
            )
        prompt_val = self.prompt.format_messages()
        self.prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response = (self.prompt | self.pipeline).invoke({})
            self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_CHAT_LECTURE_MESSAGE)
            response_with_citation = self.citation_pipeline(
                self.lecture_content,
                response,
                variant=self.variant,
                base_url=dto.settings.artemis_base_url,
            )
            self.tokens.extend(self.citation_pipeline.tokens)
            logger.info(
                "Response from lecture chat pipeline: %s",
                response_with_citation,
            )
            # Generate a session title if this is the first student message
            session_title = None
            if response_with_citation and len(dto.chat_history) == 1:
                first_user_msg = dto.chat_history[0].contents[0].text_content
                try:
                    session_title = self.session_title_pipeline(
                        first_user_msg, response_with_citation
                    )
                    if self.session_title_pipeline.tokens is not None:
                        self.tokens.append(self.session_title_pipeline.tokens)
                except Exception as e:
                    logger.error(
                        "An error occurred while running the session title generation pipeline",
                        exc_info=e,
                    )
                    traceback.print_exc()
                    self.callback.error("Generating session title failed.")
            # Complete main process
            self.callback.done(
                "Response created",
                final_result=response_with_citation,
                tokens=self.tokens,
                session_title=session_title,
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

    def _add_lecture_content_to_prompt(self, lecture_content: LectureRetrievalDTO):
        """
        Adds the relevant chunks of the lecture to the prompt
        :param lecture_content: The retrieved lecture parts
        """

        # Page chunk content
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Next you will find the relevant lecture slide content:\n"
        )
        for chunk in lecture_content.lecture_unit_page_chunks:
            text_content_msg = f" \n {chunk.page_text_content} \n"
            text_content_msg = text_content_msg.replace("{", "{{").replace("}", "}}")
            self.prompt += SystemMessagePromptTemplate.from_template(text_content_msg)

        # Transcription content
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Next you will find the relevant lecture transcription content:\n"
        )
        for _, chunk in enumerate(lecture_content.lecture_transcriptions):
            text_content_msg = f" \n {chunk.segment_text} \n"
            text_content_msg = text_content_msg.replace("{", "{{").replace("}", "}}")
            self.prompt += SystemMessagePromptTemplate.from_template(text_content_msg)

        # Segment summaries
        self.prompt += SystemMessagePromptTemplate.from_template(
            """Next you will find the relevant lecture chunks which are summaries of one lecture slide combined with the
            corresponding lecture transcription:\n"""
        )
        for chunk in lecture_content.lecture_unit_segments:
            text_content_msg = f" \n {chunk.segment_summary} \n"
            text_content_msg = text_content_msg.replace("{", "{{").replace("}", "}}")
            self.prompt += SystemMessagePromptTemplate.from_template(text_content_msg)

        self.prompt += SystemMessagePromptTemplate.from_template(
            "USE ONLY THE CONTENT YOU NEED TO ANSWER THE QUESTION:\n"
        )
