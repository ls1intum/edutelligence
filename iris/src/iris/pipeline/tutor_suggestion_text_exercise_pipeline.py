import logging
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CapabilityRequestHandler, CompletionArguments, RequirementList
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.text_exercise_prompt import (
    text_exercise_prompt,
)
from iris.pipeline.tutor_suggestion_summary_pipeline import _extract_json_from_text

logger = logging.getLogger(__name__)


def _extract_html_from_text(text: str):
    html_pattern = re.compile(
        r"\s*(?P<html>&lt;ul&gt;.*?&lt;/ul&gt;|<ul>.*?</ul>)", re.DOTALL
    )
    match = html_pattern.search(text)

    if match:
        return match.group("html").strip()
    else:
        logger.error("No HTML found after 'answer:' in text.")
        return None


def _has_html(text: str):
    """
    Check if the text contains HTML tags.
    :param text: The text to check.
    :return: True if HTML tags are found, False otherwise.
    """
    html_pattern = re.compile(r"<[^>]+>")
    return bool(html_pattern.search(text))


class TutorSuggestionTextExercisePipeline(Pipeline):

    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __init__(self):
        super().__init__(implementation_id="tutor_suggestion_text_exercise_pipeline")
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(self_hosted=False)
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_arguments=completion_args,
        )

        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Text Exercise Pipeline")
    def __call__(self, dto: TextExerciseDTO, chat_summary: str):
        result = "Error generating suggestions for text exercise"
        text_exercise_result = self._run_text_exercise_pipeline(
            dto=dto, summary=chat_summary
        )
        try:
            result = text_exercise_result
        except Exception as e:
            logger.error(f"Failed to generate suggestions for text exercise: {e}")

        return result

    def _run_text_exercise_pipeline(self, dto, summary: str):
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    text_exercise_prompt(),
                )
            ]
        )
        try:
            response = (self.prompt | self.pipeline).invoke(
                {
                    "thread_summary": summary,
                    "problem_statement": dto.problem_statement,
                    "example_solution": dto.example_solution,
                }
            )
            logger.info(response)
            json = _extract_json_from_text(response)
            try:
                result = json.get("result")
            except AttributeError:
                logger.error("No result found in JSON response.")
                return None
            if _has_html(result):
                html_response = _extract_html_from_text(result)
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
            return html_response
        except Exception as e:
            raise e
