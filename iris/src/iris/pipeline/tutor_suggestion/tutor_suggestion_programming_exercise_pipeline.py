import logging

from langsmith import traceable

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.tutor_suggestion import (
    ChannelType,
    get_chat_history_without_user_query,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.pipeline.chat.code_feedback_pipeline import CodeFeedbackPipeline
from iris.pipeline.prompts.tutor_suggestion.programming_exercise_prompt import (
    programming_exercise_prompt,
)
from iris.pipeline.tutor_suggestion.tutor_suggestion_channel_base_pipeline import (
    TutorSuggestionChannelBasePipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)


class TutorSuggestionProgrammingExercisePipeline(TutorSuggestionChannelBasePipeline):
    """
    The TutorSuggestionProgrammingExercisePipeline creates a suggestion for a programming exercise.

    When called, it uses the programming exercise DTO and chat summary to generate suggestions.
    """

    def __init__(
        self, variant: str = "default", callback: TutorSuggestionCallback = None
    ):
        super().__init__(
            implementation_id="tutor_suggestion_programming_exercise_pipeline",
            variant=variant,
            callback=callback,
            prompt=programming_exercise_prompt(),
        )

    @traceable(name="Tutor Suggestion Programming Exercise Pipeline")
    def __call__(
        self,
        lecture_content: str,
        faq_content: str,
        chat_summary: str,
        is_answered: bool,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
    ):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        :param chat_summary: summary of the chat history
        :param chat_history: history of the chat messages
        """

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
        answer, change_suggestion = self._handle_user_query(
            chat_summary,
            dto.chat_history,
            chat_type=ChannelType.PROGRAMMING_EXERCISE,
            dto=dto,
        )

        chat_history_str = get_chat_history_without_user_query(
            chat_history=dto.chat_history
        )

        additional_keys = {
            "exercise_title": exercise_title,
            "programming_language": programming_language,
            "problem_statement": problem_statement,
            "code_feedback": code_feedback_response,
        }

        html_response = self._create_tutor_suggestion(
            is_answered=is_answered,
            change_suggestion=change_suggestion,
            thread_summary=chat_summary,
            chat_history=chat_history_str,
            lecture_content=lecture_content,
            faq_content=faq_content,
            **additional_keys,
        )

        return html_response, answer
