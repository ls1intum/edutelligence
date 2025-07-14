import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.chat.code_feedback_pipeline import CodeFeedbackPipeline
from iris.pipeline.prompts.tutor_suggestion.programming_exercise_prompt import (
    programming_exercise_prompt,
)
from iris.pipeline.tutor_suggestion_summary_pipeline import _extract_json_from_text
from iris.pipeline.tutor_suggestion_text_exercise_pipeline import (
    _extract_html_from_text,
    _has_html,
)

logger = logging.getLogger(__name__)


class TutorSuggestionProgrammingExercisePipeline(Pipeline):
    """
    The TutorSuggestionProgrammingExercisePipeline creates a suggestion for a programming exercise.

    When called, it uses the programming exercise DTO and chat summary to generate suggestions.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __init__(self, variant: str = "default"):
        super().__init__(
            implementation_id="tutor_suggestion_programming_exercise_pipeline"
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=8000)

        if variant == "advanced":
            model = "deepseek-r1:8b"
        else:
            model = "gemma3:27b"

        self.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=model),
            completion_args=completion_args,
        )

        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Programming Exercise Pipeline")
    def __call__(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO, chat_summary: str
    ):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """
        logger.info("Running Tutor Suggestion Programming Exercise Pipeline")

        prompt = ChatPromptTemplate.from_messages(
            [("system", programming_exercise_prompt())]
        )
        problem_statement = dto.exercise.problem_statement
        exercise_title = dto.exercise.name
        programming_language = dto.exercise.programming_language

        code_feedback_response = "!NONE!"

        if dto.submission:
            code_feedback = CodeFeedbackPipeline(variant="default")
            query = PyrisMessage(
                sender=IrisMessageRole.USER,
                contents=[
                    TextMessageContentDTO(
                        textContent=chat_summary,
                    )
                ],
            )
            code_feedback_response = code_feedback(
                chat_history=[],
                question=query,
                repository=dto.submission.repository,
                problem_statement=dto.exercise.problem_statement,
                build_failed=dto.submission.build_failed,
                build_logs=dto.submission.build_log_entries,
                feedbacks=(
                    dto.submission.latest_result.feedbacks
                    if dto.submission and dto.submission.latest_result
                    else []
                ),
            )

        try:
            response = (prompt | self.pipeline).invoke(
                {
                    "thread_summary": chat_summary,
                    "exercise_title": exercise_title,
                    "programming_language": programming_language,
                    "problem_statement": problem_statement,
                    "code_feedback": code_feedback_response,
                }
            )
            logger.info(response)
            json = _extract_json_from_text(response)
            try:
                result = json.get("result")
            except AttributeError:
                logger.error("No result found in JSON response.")
                return "Error: Unable to parse response from language model"
            html_check = _has_html(result)
            if html_check:
                html_response = _extract_html_from_text(result)
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                )
            else:
                html_response = (
                    "<p>I was not able to answer this question based on the programming exercise.</p><br>"
                    "<p>It seems that the question is too general or not related to the programming exercise.</p>"
                )
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                )
            return html_response
        except Exception as e:
            logger.error(
                "Failed to generate suggestions for programming exercise: %s", e
            )
            return "Error generating suggestions for programming exercise"
