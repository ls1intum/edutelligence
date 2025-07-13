import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.lecture_prompt import lecture_prompt
from iris.pipeline.tutor_suggestion_summary_pipeline import _extract_json_from_text
from iris.pipeline.tutor_suggestion_text_exercise_pipeline import (
    _extract_html_from_text,
    _has_html,
)
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.vector_database.database import VectorDatabase
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)


class TutorSuggestionLecturePipeline(Pipeline):

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(self, callback: TutorSuggestionCallback, variant: str = "default"):
        super().__init__(implementation_id="tutor_suggestion_lecture_pipeline")

        completion_args = CompletionArguments(temperature=0, max_tokens=2000)

        if variant == "advanced":
            model = "gemma3:27b"
        else:
            model = "deepseek-r1:8b"

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
    def __call__(self, dto, chat_summary: str):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """
        logger.info("Running Tutor Suggestion Lecture Pipeline")

        return self._run_lecture_pipeline(dto, chat_summary)

    def _run_lecture_pipeline(self, dto, summary: str):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """

        lecture_content = self.lecture_content_retrieval(dto, summary)

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
                    "thread_summary": summary,
                }
            )
            logging.info(response)
            json = _extract_json_from_text(response)
            try:
                result = json.get("result")
            except AttributeError:
                logger.error("No result found in JSON response.")
                return None
            if _has_html(result):
                html_response = _extract_html_from_text(result)
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
            return html_response
        except Exception as e:
            logger.error("Error in Tutor Suggestion Lecture Pipeline: %s", e)
            return "Error generation suggestions for lecture"

    def lecture_content_retrieval(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO, summary: str
    ) -> str:
        """
        Retrieve content from indexed lecture content.
        This will run a RAG retrieval based on the chat history on the indexed lecture slides,
        the indexed lecture transcriptions and the indexed lecture segments,
        which are summaries of the lecture slide content and lecture transcription content from one slide a
        nd return the most relevant paragraphs.
        Use this if you think it can be useful to answer the student's question, or if the student explicitly asks
        a question about the lecture content or slides.
        Only use this once.
        """

        query = f"Return all lecture information about this discussion post {summary}"
        lecture_retrieval = LectureRetrieval(self.db.client)

        try:
            lecture_retrieval_result = lecture_retrieval(
                query=query,
                course_id=dto.course.id,
                chat_history=[],
                lecture_id=dto.lecture_id,
            )
        except AttributeError as e:
            return "Error retrieving lecture data"

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
