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
from iris.llm import CapabilityRequestHandler, CompletionArguments, RequirementList
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.post_summary_prompt import (
    post_summary_prompt,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)


def sort_post_answers(dto):
    """
    Sort the answers of the post by their id
    :param dto: execution data transfer object
    """
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


class TutorSuggestionPipeline(Pipeline):
    """
    The TutorSuggestionPipeline creates a tutor suggestion

    when called it uses the post received as an argument to create a suggestion based on the conversation
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(self, callback: TutorSuggestionCallback):
        super().__init__(implementation_id="tutor_suggestion_pipeline")
        completion_args = CompletionArguments()
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(self_hosted=True)
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=completion_args,
        )
        self.callback = callback
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Pipeline")
    def __call__(self, dto: CommunicationTutorSuggestionPipelineExecutionDTO):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """
        self.callback.in_progress("Summarizing post content")
        dto = sort_post_answers(dto=dto)
        summary = self._run_tutor_suggestion_pipeline(dto=dto)
        self.callback.in_progress("Generated summary of post")
        try:
            post_summary = summary.get("summary")
        except AttributeError:
            post_summary = None
        self.callback.done(
            "Generated tutor suggestions",
            artifact=post_summary,
            tokens=self.tokens,
        )

    def _run_tutor_suggestion_pipeline(self, dto):
        """
        Run the tutor suggestion pipeline.
        :param dto: execution data transfer object
        :return: the generated summary
        """
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    post_summary_prompt(dto.post),
                ),
            ]
        )
        for i in range(len(dto.post.answers)):
            answer = dto.post.answers[i]
            if answer is not None:
                logger.info(answer.id)
                logger.info(answer.content)
        logger.info(post_summary_prompt(dto.post))
        try:
            response = (self.prompt | self.pipeline).invoke({})
            logger.info(response)
            json_response = _extract_json_from_text(response)
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
            )
            return json_response
        except Exception as e:
            raise e
