import logging
from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pyris_message import PyrisMessage
from iris.common.tutor_suggestion import (
    ChannelType,
    extract_json_from_text,
    get_last_artifact,
    get_user_query,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.programming_exercise_query_prompt import (
    programming_exercise_query_prompt,
)
from iris.pipeline.prompts.tutor_suggestion.text_exercise_query_prompt import (
    text_exercise_query_prompt,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"


class TutorSuggestionUserQueryPipeline(Pipeline):
    """
    The TutorSuggestionUserQueryPipeline processes user queries in the context of a text exercise.
    It generates answers based on the chat summary, chat history, and text exercise DTO.

    When called, it uses the user query and last suggestion from the chat history to generate a response.
    It utilizes a language model to process the input and generate a structured response.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback
    chat_type: str

    def __init__(
        self,
        variant: str = "default",
        chat_type: str = ChannelType.TEXT_EXERCISE,
        callback: TutorSuggestionCallback = None,
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
        self.chat_type = chat_type

        # Prompt template for user query
        if chat_type == ChannelType.TEXT_EXERCISE:
            self.query_prompt_template = ChatPromptTemplate.from_messages(
                [("system", text_exercise_query_prompt())]
            )
        elif chat_type == ChannelType.PROGRAMMING_EXERCISE:
            self.query_prompt_template = ChatPromptTemplate.from_messages(
                [("system", programming_exercise_query_prompt())]
            )

    @traceable(name="Tutor Suggestion User Query Pipeline")
    def __call__(
        self,
        chat_summary: str,
        chat_history: List[PyrisMessage],
        chat_history_without_user_query_str: str,
        dto: TextExerciseDTO = None,
        communication_dto: CommunicationTutorSuggestionPipelineExecutionDTO = None,
        code_feedback: str = None,
    ):
        """
        Run the pipeline to generate an answer for the user query.
        :param chat_summary: Summary of the chat.
        :param chat_history: List of messages in the chat history.
        :param chat_history_without_user_query_str: Chat history without the user query.
        :param dto: TextExerciseDTO containing problem statement and example solution.
        :param communication_dto: Communication data transfer object for programming exercises.
        :param code_feedback: Feedback on the code for programming exercises.
        :return: A tuple containing the generated answer and a suggestion for changes.
        :raises: Exception if the answer generation fails.
        """

        answer = ""
        change_suggestion = ""

        self.callback.in_progress("Generating answer for user query")
        user_query = get_user_query(chat_history=chat_history)
        last_suggestion = get_last_artifact(chat_history=chat_history)

        base_keys = {
            "user_query": user_query,
            "suggestion": last_suggestion,
            "thread_summary": chat_summary,
            "chat_history": chat_history_without_user_query_str,
            "lecture_contents": "",
        }
        try:
            if self.chat_type == ChannelType.TEXT_EXERCISE:
                prompt_input = {
                    **base_keys,
                    "problem_statement": dto.problem_statement,
                    "example_solution": dto.example_solution,
                }
            elif self.chat_type == ChannelType.PROGRAMMING_EXERCISE:
                prompt_input = {
                    **base_keys,
                    "problem_statement": communication_dto.exercise.problem_statement,
                    "exercise_title": communication_dto.exercise.name,
                    "programming_language": communication_dto.exercise.programming_language,
                    "code_feedback": code_feedback,
                }
            else:
                prompt_input = {
                    **base_keys,
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
