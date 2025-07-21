import logging
from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pyris_message import PyrisMessage
from iris.common.tutor_suggestion_helper import (
    get_last_artifact,
    get_user_query, extract_json_from_text,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.text_exercise_query_prompt import (
    text_exercise_query_prompt,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"


class TutorSuggestionUserQueryPipeline(Pipeline):

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(
        self,
        variant: str = "default",
        callback: TutorSuggestionCallback = None,
        chat_type: str = "text_exercise",
    ):
        super().__init__(implementation_id="tutor_suggestion_user_query_pipeline")
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

        # Prompt template for user query
        if chat_type == "text_exercise":
            self.query_prompt_template = ChatPromptTemplate.from_messages(
                [("system", text_exercise_query_prompt())]
            )

    @traceable(name="Tutor Suggestion User Query Pipeline")
    def __call__(
        self,
        chat_summary: str,
        chat_history: List[PyrisMessage],
        dto: TextExerciseDTO,
        chat_history_without_user_query_str: str,
    ):

        answer = ""
        change_suggestion = ""

        self.callback.in_progress("Generating answer for user query")
        user_query = get_user_query(chat_history=chat_history)
        last_suggestion = get_last_artifact(chat_history=chat_history)

        base_keys = {
            "thread_summary": chat_summary,
            "problem_statement": dto.problem_statement,
            "example_solution": dto.example_solution,
            "chat_history": chat_history_without_user_query_str,
            "lecture_contents": "",
        }
        try:
            prompt_input = {
                **base_keys,
                "user_query": user_query,
                "suggestion": last_suggestion,
            }
            response = (self.query_prompt_template | self.pipeline).invoke(prompt_input)
            logger.info(response)
            json = extract_json_from_text(response)
            try:
                answer = json.get("reply")
                change_suggestion = json.get("suggestion_prompt")
            except AttributeError:
                logger.error("No answer found in JSON response.")
        except Exception as e:
            logger.error("Failed to generate answer for user query: %s", e)
            return "Error generating answer for user query"
        return answer, change_suggestion
