import logging
from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import PyrisMessage
from iris.common.tutor_suggestion_helper import (
    extract_html_from_text,
    extract_json_from_text,
    get_chat_history_without_user_query,
    has_html,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.text_exercise_prompt import (
    text_exercise_prompt,
)
from iris.pipeline.tutor_suggestion.tutor_suggestion_user_query_pipeline import (
    TutorSuggestionUserQueryPipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"


class TutorSuggestionTextExercisePipeline(Pipeline):
    """
    The TutorSuggestionTextExercisePipeline creates a suggestion for a text exercise.

    When called, it uses the text exercise DTO and chat summary to generate suggestions
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(
        self, variant: str = "default", callback: TutorSuggestionCallback = None
    ):
        super().__init__(implementation_id="tutor_suggestion_text_exercise_pipeline")
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

        self.output_parser = StrOutputParser()
        self.pipeline = self.llm | self.output_parser
        self.tokens = []
        self.callback = callback

        # Prompt template for text exercise suggestions
        self.text_prompt_template = ChatPromptTemplate.from_messages(
            [("system", text_exercise_prompt())]
        )

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Text Exercise Pipeline")
    def __call__(
        self,
        dto: TextExerciseDTO,
        chat_summary: str,
        chat_history: List[PyrisMessage],
        is_answered: bool,
    ):
        answer = ""
        change_suggestion = ""

        chat_history_str = get_chat_history_without_user_query(
            chat_history=chat_history
        )

        if chat_history and chat_history[-1].sender == "USER":
            user_query_pipeline = TutorSuggestionUserQueryPipeline(
                variant=self.variant, callback=self.callback
            )
            answer, change_suggestion = user_query_pipeline(
                dto=dto,
                chat_summary=chat_summary,
                chat_history=chat_history,
                chat_history_without_user_query_str=chat_history_str,
            )

        if "NO" not in change_suggestion:

            base_keys = {
                "thread_summary": chat_summary,
                "problem_statement": dto.problem_statement,
                "example_solution": dto.example_solution,
                "chat_history": chat_history_str,
            }
            prompt_input = {
                **base_keys,
                "user_query": change_suggestion,
            }
            try:
                response = (self.text_prompt_template | self.pipeline).invoke(
                    prompt_input
                )
                logger.info(response)
                json = extract_json_from_text(response)
                try:
                    result = json.get("result")
                except AttributeError:
                    logger.error("No result found in JSON response.")
                    return None
                if has_html(result):
                    html_response = result
                    extracted = extract_html_from_text(result)
                    if extracted:
                        html_response = extracted
                    if is_answered:
                        is_answered_html = """<p class="generated-suggestion-text">I think that the discussion is
                        already answered before. I suggest marking it as solved. Here are still some suggestions for
                        you:</p>"""
                        is_answered_html = extract_html_from_text(is_answered_html)
                        html_response = is_answered_html + html_response
                    self._append_tokens(
                        self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                    )
                else:
                    html_response = (
                        "<p>I was not able to answer this question based on the text exercise.</p><br>"
                        "<p>It seems that the question is too general or not related to the text exercise."
                        "</p>"
                    )
                    self._append_tokens(
                        self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                    )

                return html_response, answer
            except Exception as e:
                raise e
        return None, answer
