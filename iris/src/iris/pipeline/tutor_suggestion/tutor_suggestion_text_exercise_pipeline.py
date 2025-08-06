import logging
from typing import List

from langsmith import traceable

from iris.common.pyris_message import PyrisMessage
from iris.common.tutor_suggestion import (
    ChannelType,
    get_chat_history_without_user_query,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.pipeline.prompts.tutor_suggestion.text_exercise_prompt import (
    text_exercise_prompt,
)
from iris.pipeline.tutor_suggestion.tutor_suggestion_channel_base_pipeline import (
    TutorSuggestionChannelBasePipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)


class TutorSuggestionTextExercisePipeline(TutorSuggestionChannelBasePipeline):
    """
    The TutorSuggestionTextExercisePipeline creates a suggestion for a text exercise.

    When called, it uses the text exercise DTO and chat summary to generate suggestions
    """

    def __init__(
        self, variant: str = "default", callback: TutorSuggestionCallback = None
    ):
        super().__init__(
            implementation_id="tutor_suggestion_text_exercise_pipeline",
            variant=variant,
            callback=callback,
            prompt=text_exercise_prompt(),
        )

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Text Exercise Pipeline")
    def __call__(
        self,
        lecture_content: str,
        faq_content: str,
        chat_summary: str,
        is_answered: bool,
        dto: TextExerciseDTO,
        chat_history: List[PyrisMessage],
    ):

        chat_history_str = get_chat_history_without_user_query(
            chat_history=chat_history
        )

        answer, change_suggestion = self._handle_user_query(
            chat_summary,
            chat_history,
            text_exercise_dto=dto,
            chat_type=ChannelType.TEXT_EXERCISE,
            lecture_content=lecture_content,
            faq_content=faq_content,
        )

        additional_keys = {
            "problem_statement": dto.problem_statement,
            "example_solution": dto.example_solution,
        }

        html_response = self._create_tutor_suggestion(
            is_answered=is_answered,
            change_suggestion=change_suggestion,
            thread_summary=chat_summary,
            chat_history=chat_history_str,
            faq_content=faq_content,
            lecture_content=lecture_content,
            **additional_keys,
        )
        return html_response, answer
