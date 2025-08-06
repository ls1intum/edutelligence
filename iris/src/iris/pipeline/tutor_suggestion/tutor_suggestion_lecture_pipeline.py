import logging

from langsmith import traceable

from iris.common.tutor_suggestion import (
    ChannelType,
    get_chat_history_without_user_query,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.pipeline.prompts.tutor_suggestion.suggestion_prompts import lecture_prompt
from iris.pipeline.tutor_suggestion.tutor_suggestion_channel_base_pipeline import (
    TutorSuggestionChannelBasePipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)


class TutorSuggestionLecturePipeline(TutorSuggestionChannelBasePipeline):
    """
    Tutor Suggestion Lecture Pipeline.
    This pipeline is used to generate suggestions for tutors based on lecture content.
    It retrieves relevant lecture content and generates a response using an LLM.
    """

    def __init__(self, callback: TutorSuggestionCallback, variant: str = "default"):
        super().__init__(
            implementation_id="tutor_suggestion_lecture_pipeline",
            variant=variant,
            callback=callback,
            prompt=lecture_prompt(),
        )

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Lecture Pipeline")
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
        """
        answer, change_suggestion = self._handle_user_query(
            chat_summary=chat_summary,
            chat_history=dto.chat_history,
            chat_type=ChannelType.LECTURE,
            dto=dto,
            lecture_content=lecture_content,
            faq_content=faq_content,
        )

        chat_history_str = get_chat_history_without_user_query(
            chat_history=dto.chat_history
        )

        html_response = self._create_tutor_suggestion(
            is_answered=is_answered,
            change_suggestion=change_suggestion,
            thread_summary=chat_summary,
            chat_history=chat_history_str,
            lecture_content=lecture_content,
            faq_content=faq_content,
        )

        return html_response, answer
