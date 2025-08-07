import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.tutor_suggestion import (ChannelType, extract_html_from_text,
                                          extract_json_from_text,
                                          extract_list_html_from_text,
                                          get_chat_history_without_user_query,
                                          has_html)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import \
    CommunicationTutorSuggestionPipelineExecutionDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.chat.code_feedback_pipeline import CodeFeedbackPipeline
from iris.pipeline.prompts.tutor_suggestion.suggestion_prompts import (
    lecture_prompt, programming_exercise_prompt, text_exercise_prompt)
from iris.pipeline.tutor_suggestion.tutor_suggestion_user_query_pipeline import \
    TutorSuggestionUserQueryPipeline
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
        variant: str = "default",
        callback: TutorSuggestionCallback = None,
    ):
        super().__init__(implementation_id="tutor_suggestion_pipeline")
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

    @traceable(name="Tutor Suggestion Pipeline")
    def __call__(
        self,
        channel_type: str,
        lecture_content: str,
        faq_content: str,
        chat_summary: str,
        is_answered: bool,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
    ):
        additional_keys = {}
        if channel_type == ChannelType.TEXT_EXERCISE:
            self.prompt = ChatPromptTemplate.from_messages(
                [("system", text_exercise_prompt())]
            )
            if dto.text_exercise is None:
                raise ValueError("Text exercise DTO cannot be None")
            additional_keys = {
                "problem_statement": dto.text_exercise.problem_statement,
                "example_solution": dto.text_exercise.example_solution,
            }
        elif channel_type == ChannelType.PROGRAMMING_EXERCISE:
            self.prompt = ChatPromptTemplate.from_messages(
                [("system", programming_exercise_prompt())]
            )
            problem_statement = dto.programming_exercise.problem_statement
            exercise_title = dto.programming_exercise.name
            programming_language = dto.programming_exercise.programming_language

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
                    problem_statement=dto.programming_exercise.problem_statement,
                    build_failed=dto.submission.build_failed,
                    build_logs=dto.submission.build_log_entries,
                    feedbacks=(
                        dto.submission.latest_result.feedbacks
                        if dto.submission and dto.submission.latest_result
                        else []
                    ),
                )
            additional_keys = {
                "exercise_title": exercise_title,
                "programming_language": programming_language,
                "problem_statement": problem_statement,
                "code_feedback": code_feedback_response,
            }

        elif channel_type == ChannelType.LECTURE:
            self.prompt = ChatPromptTemplate.from_messages(
                [("system", lecture_prompt())]
            )

        answer, change_suggestion = self._handle_user_query(
            chat_summary=chat_summary,
            chat_history=dto.chat_history,
            chat_type=channel_type,
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
            **additional_keys,
        )

        return html_response, answer

    def _handle_user_query(
        self,
        chat_summary: str,
        chat_history: list[PyrisMessage],
        chat_type: str,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO = None,
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
                dto=dto.text_exercise,
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
            return self.callback.error("Error in Tutor Suggestion Pipeline")
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
