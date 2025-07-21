import json
import logging
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.post_summary_prompt import (
    post_summary_prompt,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"

def sort_post_answers(dto):
    """
    Sort the answers of the post by their id
    :param dto: execution data transfer object
    """
    if dto.post is None or dto.post.answers is None:
        return dto
    dto.post.answers.sort(key=lambda x: x.id)
    return dto


def _extract_json_from_text(text: str):
    """
    Extracts the JSON string from the given text.
    This function uses a regular expression to find the JSON string
    and then attempts to parse it into a Python dictionary.
    :param text: The input text containing the JSON string.
    :return: A dictionary representation of the JSON string, or None if parsing fails.
    :raises json.JSONDecodeError: If the JSON string cannot be parsed.
    """
    json_pattern = re.compile(r"\{.*?\}", re.DOTALL | re.MULTILINE)
    matches = json_pattern.findall(text)

    if matches:
        json_str = matches[-1]
        try:
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError as e:
            logger.error("JSON decoding failed: %s", e)
            return None
    return None


class TutorSuggestionSummaryPipeline(Pipeline):
    """
    The TutorSuggestionSummaryPipeline creates a summary of the post
    when called it uses the post received as an argument to create a summary based on the conversation.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(
        self,
        callback: TutorSuggestionCallback,
        variant: str = "default",
    ):
        super().__init__(implementation_id="tutor_suggestion_summary_pipeline")
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)

        if variant == "advanced":
            model = ADVANCED_VARIANT
        else:
            model = DEFAULT_VARIANT

        self.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=model),
            completion_args=completion_args,
        )

        self.callback = callback
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []
        self.prompt = None

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Summary Pipeline")
    def __call__(self, dto: CommunicationTutorSuggestionPipelineExecutionDTO):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        :return: json of the summary of the post in the form
        {"summary": "<summary>", "is_question": "<is_question>"}
        """
        dto = sort_post_answers(dto=dto)
        summary = self._run_tutor_suggestion_summary_pipeline(dto=dto)

        return summary

    def _run_tutor_suggestion_summary_pipeline(self, dto):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        :return: summary of the post
        """
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    post_summary_prompt(dto.post),
                ),
            ]
        )
        try:
            response = (self.prompt | self.pipeline).invoke({})
            logging.info(response)
            json_response = _extract_json_from_text(response)
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
            )
            if json_response is not None:
                json_response["num_answers"] = len(dto.post.answers)
            return json_response
        except Exception as e:
            raise e
