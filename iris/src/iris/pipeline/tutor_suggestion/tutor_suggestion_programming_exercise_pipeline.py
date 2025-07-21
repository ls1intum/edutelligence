import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.tutor_suggestion import (
    ChannelType,
    extract_html_from_text,
    extract_json_from_text,
    get_chat_history_without_user_query,
    has_html,
)
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
from iris.pipeline.tutor_suggestion.tutor_suggestion_user_query_pipeline import (
    TutorSuggestionUserQueryPipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"


class TutorSuggestionProgrammingExercisePipeline(Pipeline):
    """
    The TutorSuggestionProgrammingExercisePipeline creates a suggestion for a programming exercise.

    When called, it uses the programming exercise DTO and chat summary to generate suggestions.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __init__(
        self, variant: str = "default", callback: TutorSuggestionCallback = None
    ):
        super().__init__(
            implementation_id="tutor_suggestion_programming_exercise_pipeline"
        )
        self.variant = variant
        completion_args = CompletionArguments(temperature=0, max_tokens=8000)

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

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Programming Exercise Pipeline")
    def __call__(
        self,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
        chat_summary: str,
        chat_history: list[PyrisMessage],
    ):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        :param chat_summary: summary of the chat history
        :param chat_history: history of the chat messages
        """
        answer = ""
        change_suggestion = ""

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

        chat_history_str = get_chat_history_without_user_query(
            chat_history=chat_history,
        )

        if chat_history and chat_history[-1].sender == IrisMessageRole.USER:
            user_query_pipeline = TutorSuggestionUserQueryPipeline(
                variant=self.variant,
                callback=self.callback,
                chat_type=ChannelType.PROGRAMMING_EXERCISE,
            )
            answer, change_suggestion = user_query_pipeline(
                communication_dto=dto,
                chat_summary=chat_summary,
                chat_history=chat_history,
                chat_history_without_user_query_str=chat_history_str,
                code_feedback=code_feedback_response,
            )

        if "NO" not in change_suggestion:

            prompt_input = {
                "thread_summary": chat_summary,
                "exercise_title": exercise_title,
                "programming_language": programming_language,
                "problem_statement": problem_statement,
                "code_feedback": code_feedback_response,
            }

            prompt = ChatPromptTemplate.from_messages(
                [("system", programming_exercise_prompt())]
            )

            try:
                response = (prompt | self.pipeline).invoke(prompt_input)
                logger.info(response)
                json = extract_json_from_text(response)
                try:
                    result = json.get("result")
                except AttributeError:
                    logger.error("No result found in JSON response.")
                    return "Error: Unable to parse response from language model"
                if has_html(result):
                    html_response = extract_html_from_text(result)
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
                return html_response, answer
            except Exception as e:
                logger.error(
                    "Failed to generate suggestions for programming exercise: %s", e
                )
                return "Error generating suggestions for programming exercise"
        return None, answer
