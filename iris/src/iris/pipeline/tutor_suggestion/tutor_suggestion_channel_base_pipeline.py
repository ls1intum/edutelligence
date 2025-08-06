import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.tutor_suggestion import (
    extract_html_from_text,
    extract_json_from_text,
    extract_list_html_from_text,
    has_html,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.tutor_suggestion.tutor_suggestion_user_query_pipeline import (
    TutorSuggestionUserQueryPipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"

logger = logging.getLogger(__name__)


class TutorSuggestionChannelBasePipeline(Pipeline):
    """
    Base class for tutor suggestion channel pipelines.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(
        self,
        prompt: str,
        implementation_id: str,
        variant: str = "default",
        callback: TutorSuggestionCallback = None,
    ):
        super().__init__(implementation_id=implementation_id)
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
        self.prompt = ChatPromptTemplate.from_messages([("system", prompt)])

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(self):
        raise NotImplementedError("This method should be implemented in subclasses.")

    def _handle_user_query(
        self,
        chat_summary: str,
        chat_history: list[PyrisMessage],
        chat_type: str,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO = None,
        text_exercise_dto: TextExerciseDTO = None,
        lecture_content: str = None,
        faq_content: str = None,
    ):
        answer = ""
        change_suggestion = ""
        if chat_history and chat_history[-1].sender == IrisMessageRole.USER:
            user_query_pipeline = TutorSuggestionUserQueryPipeline(
                variant=self.variant, callback=self.callback, chat_type=chat_type
            )

            answer, change_suggestion = user_query_pipeline(
                dto=text_exercise_dto,
                chat_summary=chat_summary,
                chat_history=chat_history,
                communication_dto=dto,
                lecture_contents=lecture_content,
                faq_contents=faq_content,
            )
        return answer, change_suggestion

    def _create_tutor_suggestion(
        self,
        is_answered: bool,
        change_suggestion: str,
        thread_summary: str,
        chat_history: str,
        lecture_content: str,
        faq_content: str,
        **additional_keys,
    ):
        if "NO" not in change_suggestion:
            self.callback.in_progress("Generating suggestions for tutor")

            base_keys = {
                "thread_summary": thread_summary,
                "chat_history": chat_history,
                "user_query": change_suggestion,
                "lecture_content": lecture_content,
                "faq_content": faq_content,
            }
            prompt_input = {
                **base_keys,
                **additional_keys,
            }
            try:
                response = (self.prompt | self.pipeline).invoke(prompt_input)
                logger.info(response)
                html_response = self._handle_suggestion_response(response, is_answered)

                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                )

                return html_response
            except Exception as e:
                logger.error("Error in Tutor Suggestion Pipeline: %s", e)
                raise e
        return None

    def _handle_suggestion_response(self, response: str, is_answered: bool) -> str:
        json = extract_json_from_text(response)
        try:
            result = json.get("result")
        except AttributeError:
            logger.error("No result found in JSON response.")
            return ""
        if has_html(result):
            html_response = result
            extracted = extract_list_html_from_text(result)
            if extracted:
                html_response = extracted
            if is_answered:
                is_answered_html = """<p class="generated-suggestion-text">I think that the discussion is \
                                        already answered before. I suggest marking it as solved. Here are still some\
                                         suggestions for you:</p>"""
                is_answered_html = extract_html_from_text(is_answered_html)
                html_response = is_answered_html + html_response
        else:
            html_response = (
                "<p>I was not able to answer this question based on the text exercise.</p><br>"
                "<p>It seems that the question is too general or not related to the text exercise."
                "</p>"
            )
        return html_response
