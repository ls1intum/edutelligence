import logging
from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import PyrisMessage, IrisMessageRole
from iris.common.tutor_suggestion import (
    extract_html_from_text,
    extract_json_from_text,
    has_html, ChannelType,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.lecture_prompt import lecture_prompt
from iris.pipeline.tutor_suggestion.tutor_suggestion_user_query_pipeline import TutorSuggestionUserQueryPipeline
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.vector_database.database import VectorDatabase
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"

class TutorSuggestionLecturePipeline(Pipeline):
    """
    Tutor Suggestion Lecture Pipeline.
    This pipeline is used to generate suggestions for tutors based on lecture content.
    It retrieves relevant lecture content and generates a response using an LLM.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(self, callback: TutorSuggestionCallback, variant: str = "default"):
        super().__init__(implementation_id="tutor_suggestion_lecture_pipeline")
        self.variant = variant

        completion_args = CompletionArguments(temperature=0, max_tokens=2000)

        if variant == "advanced":
            model = ADVANCED_VARIANT
        else:
            model = DEFAULT_VARIANT

        self.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=model),
            completion_args=completion_args,
        )

        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []
        self.callback = callback
        self.db = VectorDatabase()

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Lecture Pipeline")
    def __call__(
        self,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
        chat_summary: str
    ):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """
        answer = ""
        change_suggestion = ""

        lecture_content = self.lecture_content_retrieval(dto, chat_summary)


        if dto.chat_history and dto.chat_history[-1].sender == IrisMessageRole.USER:
            user_query_pipeline = TutorSuggestionUserQueryPipeline(
                variant=self.variant, callback=self.callback, chat_type=ChannelType.LECTURE
            )
            answer, change_suggestion = user_query_pipeline(
                communication_dto=dto,
                chat_summary=chat_summary,
                chat_history=dto.chat_history,
            )

        if "NO" not in change_suggestion:
            self.callback.in_progress("Generating suggestions for lecture")

            self.prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        lecture_prompt(),
                    ),
                ]
            )

            try:
                response = (self.prompt | self.pipeline).invoke(
                    {
                        "lecture_content": lecture_content,
                        "thread_summary": chat_summary,
                    }
                )
                logging.info(response)
                json = extract_json_from_text(response)
                try:
                    result = json.get("result")
                except AttributeError:
                    logger.error("No result found in JSON response.")
                    return None
                if has_html(result):
                    html_response = extract_html_from_text(result)
                    self._append_tokens(
                        self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                    )
                else:
                    html_response = (
                        "<p>I was not able to answer this question based on the lecture.</p><br>"
                        "<p>It seems that the question is too general or not related to this lecture."
                        "</p>"
                    )
                    self._append_tokens(
                        self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                    )
                return html_response, answer
            except Exception as e:
                logger.error("Error in Tutor Suggestion Lecture Pipeline: %s", e)
                return "Error generation suggestions for lecture"
        return None, answer

    def lecture_content_retrieval(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO, summary: str
    ) -> str:
        """
        Retrieve content from indexed lecture content.
        This will run a RAG retrieval based on the chat history on the indexed lecture slides,
        the indexed lecture transcriptions and the indexed lecture segments,
        which are summaries of the lecture slide content and lecture transcription content from one slide
        and return the most relevant paragraphs.
        """
        self.callback.in_progress("Running lecture content retrieval")

        query = (f"I want to understand the following summarized discussion better: {summary}\n. What are the relevant"
                 f" lecture slides, transcriptions and segments that I can use to answer the question?")
        lecture_retrieval = LectureRetrieval(self.db.client)

        try:
            lecture_retrieval_result = lecture_retrieval(
                query=query,
                course_id=dto.course.id,
                chat_history=[],
                lecture_id=dto.lecture_id,
            )
        except AttributeError as e:
            return "Error retrieving lecture data: " + str(e)

        result = "Lecture slide content:\n"
        for paragraph in lecture_retrieval_result.lecture_unit_page_chunks:
            lct = (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.page_text_content}---\n\n"
            )
            result += lct

        result += "Lecture transcription content:\n"
        for paragraph in lecture_retrieval_result.lecture_transcriptions:
            transcription = (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_text}---\n\n"
            )
            result += transcription

        result += "Lecture segment content:\n"
        for paragraph in lecture_retrieval_result.lecture_unit_segments:
            segment = (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_summary}---\n\n"
            )
            result += segment
        return result
