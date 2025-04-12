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
from iris.pipeline.prompts.tutor_suggestion.summary_and_context_prompt import (
    summary_and_context_prompt,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)


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
        summary_with_category = self._run_tutor_suggestion_pipeline(dto=dto)
        self.callback.in_progress("Generated summary with context of post")
        try:
            post_category = summary_with_category.get("category")
        except AttributeError:
            post_category = None
        try:
            post_summary = summary_with_category.get("summary")
        except AttributeError:
            post_summary = None
        self.callback.in_progress(f"Message is in category {post_category}")
        if post_category == "EXERCISE":
            logger.info("Working with exercise")
        elif post_category == "LECTURE":
            logger.info("Working with lecture")
        elif post_category == "EXERCISE_LECTURE":
            logger.info("Working with exercise and lecture")
        elif post_category == "ORGANIZATION":
            logger.info("Working with organization")
        elif post_category == "SPAM":
            logger.info("Working with spam")
        else:
            logger.info("Cannot categorize")
        self.callback.done(
            "Generated tutor suggestions",
            final_result=post_summary,
            tokens=self.tokens,
        )

    def _run_tutor_suggestion_pipeline(self, dto):
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    summary_and_context_prompt(dto.post),
                ),
            ]
        )
        try:
            response = (self.prompt | self.pipeline).invoke({})
            json_response = self._extract_json_from_text(response)
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
            )
            return json_response
        except Exception as e:
            raise e

    @staticmethod
    def _extract_json_from_text(text: str):
        # Find the first JSON object in the text using a regular expression
        json_pattern = re.compile(r"\{.*?\}", re.DOTALL)
        match = json_pattern.search(text)

        if match:
            json_str = match.group()
            try:
                data = json.loads(json_str)
                return data
            except json.JSONDecodeError as e:
                print("JSON decoding failed:", e)
                return None
        else:
            print("No JSON found in text.")
            return None
